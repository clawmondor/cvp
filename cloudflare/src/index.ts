import { Container, getContainer } from "@cloudflare/containers";

interface Env {
  CUSTOM_PYTHON_AGENT: DurableObjectNamespace<CustomPythonAgent>;
  LAUNCH_HMAC_SECRET: string;
  CVP_BASE_URL: string;
  CVP_AGENT_KEY: string;
  OPENROUTER_API_KEY: string;
  BROWSER_RUN_ACCOUNT_ID: string;
  BROWSER_RUN_TOKEN: string;
}

interface Job {
  run_id: string;
  matter_id: string;
  item_id: string;
  model_slug: string;
  agent_impl: string;
}

export class CustomPythonAgent extends Container<Env> {
  // The run is a one-shot batch job: no port, no request forwarding.
  sleepAfter = "30s";
  private launched = false;

  async launch(job: Job, secrets: Record<string, string>): Promise<void> {
    // The DO id IS the run id, so a replayed launch lands here and is refused.
    if (this.launched) return;
    this.launched = true;
    const container = this.ctx.container;
    if (!container) throw new Error("no container is attached to this Durable Object");
    await container.start({
      enableInternet: true,
      env: {
        RUN_ID: job.run_id,
        MATTER_ID: job.matter_id,
        ITEM_ID: job.item_id,
        MODEL_SLUG: job.model_slug,
        ...secrets,
      },
    });
  }
}

/**
 * Verify the HMAC CVP signed over "<timestamp>.<body>".
 * Must stay identical to sign_payload() in src/cvp/services/agent_launch.py —
 * the fixed vector in tests/test_agent_launch_signing.py is the shared contract.
 *
 * Vector (verified in both Python and Node — see Task 14 report):
 *   secret="topsecret" timestamp="1757462400" body={"run_id":"abc"}
 *   -> v1=a3e15302f3da219c4094cc60fc43f2bc5d694071dc2d6664006f1b55ff891fd3
 */
async function verify(req: Request, secret: string): Promise<string | null> {
  const ts = req.headers.get("X-CVP-Timestamp");
  const sig = req.headers.get("X-CVP-Signature");
  if (!ts || !sig) return null;

  const skew = Math.abs(Date.now() / 1000 - Number(ts));
  if (!Number.isFinite(skew) || skew > 300) return null;

  const body = await req.text();
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const mac = await crypto.subtle.sign("HMAC", key, enc.encode(`${ts}.${body}`));
  const hex = [...new Uint8Array(mac)]
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  const expected = `v1=${hex}`;

  if (sig.length !== expected.length) return null;
  let diff = 0;
  for (let i = 0; i < sig.length; i++) diff |= sig.charCodeAt(i) ^ expected.charCodeAt(i);
  return diff === 0 ? body : null;
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    if (req.method !== "POST" || url.pathname !== "/runs") {
      return new Response("not found", { status: 404 });
    }

    const body = await verify(req, env.LAUNCH_HMAC_SECRET);
    if (body === null) return new Response("unauthorized", { status: 401 });

    let job: Job;
    try {
      job = JSON.parse(body) as Job;
    } catch {
      return new Response("bad request", { status: 400 });
    }
    if (!job.run_id || !job.item_id || !job.model_slug) {
      return new Response("bad request", { status: 400 });
    }

    const stub = getContainer(env.CUSTOM_PYTHON_AGENT, job.run_id);
    await stub.launch(job, {
      CVP_BASE_URL: env.CVP_BASE_URL,
      CVP_AGENT_KEY: env.CVP_AGENT_KEY,
      OPENROUTER_API_KEY: env.OPENROUTER_API_KEY,
      BROWSER_RUN_ACCOUNT_ID: env.BROWSER_RUN_ACCOUNT_ID,
      BROWSER_RUN_TOKEN: env.BROWSER_RUN_TOKEN,
    });

    return new Response(JSON.stringify({ accepted: job.run_id }), {
      status: 202,
      headers: { "Content-Type": "application/json" },
    });
  },
};
