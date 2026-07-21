import pytest

import claimos.models  # noqa: F401
import claimos.models_access  # noqa: F401
import claimos.models_audit  # noqa: F401
import claimos.models_auth  # noqa: F401
import claimos.models_comments  # noqa: F401
import claimos.models_feedback  # noqa: F401
import claimos.models_grants  # noqa: F401
import claimos.models_vision  # noqa: F401

# Ensure all tables exist on the shared real-DB engine so that tests which
# exercise code paths that call SessionLocal() directly (e.g. write_audit_log)
# don't fail with "no such table".  Base.metadata is fully populated at this
# point because all model modules have been imported above.
from claimos.db import engine
from claimos.models import Base
from claimos.services import access_cache as _access_cache

Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def _clear_access_cache():
    """The claim-access cache is a process-global dict; clear it between tests
    so that an authorization decision from one test never leaks into another."""
    _access_cache._cache.clear()
    yield
    _access_cache._cache.clear()
