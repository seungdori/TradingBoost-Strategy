# src/core/config.py - Deprecation Shim
#
# DEPRECATED: This module is deprecated and will be removed in a future version.
# Please use: from shared.config import settings
#
# This file exists for backward compatibility only.

import warnings
from shared.config import settings, get_settings

# Issue deprecation warning on import
warnings.warn(
    "HYPERRSI.src.core.config is deprecated. "
    "Use 'from shared.config import settings' instead.",
    DeprecationWarning,
    stacklevel=2
)

# Re-export for backward compatibility
API_BASE_URL = "/api"

# All settings are now accessed through shared.config
__all__ = ['settings', 'get_settings', 'API_BASE_URL']
