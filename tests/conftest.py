import pytest

import cvp.models  # noqa: F401
import cvp.models_access  # noqa: F401
import cvp.models_audit  # noqa: F401
import cvp.models_auth  # noqa: F401
import cvp.models_comments  # noqa: F401
import cvp.models_feedback  # noqa: F401
import cvp.models_vision  # noqa: F401

# Ensure all tables exist on the shared real-DB engine so that tests which
# exercise code paths that call SessionLocal() directly (e.g. write_audit_log)
# don't fail with "no such table".  Base.metadata is fully populated at this
# point because all model modules have been imported above.
from cvp.db import engine
from cvp.models import Base
from cvp.services import access_cache as _access_cache

Base.metadata.create_all(engine)


@pytest.fixture(autouse=True)
def _clear_access_cache():
    """The matter-access cache is a process-global dict; clear it between tests
    so that an authorization decision from one test never leaks into another."""
    _access_cache._cache.clear()
    yield
    _access_cache._cache.clear()
