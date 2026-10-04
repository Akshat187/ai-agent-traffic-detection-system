"""
Single source of truth for every version string in WebSense.

Import from here instead of hard-coding versions in the engine, config, DB
defaults or the SDK response. Bump these when the corresponding contract
changes:

  APP_VERSION             API / package release
  MODEL_VERSION           detection engine behaviour (any verdict-affecting change)
  FEATURE_SCHEMA_VERSION  feature-vector layout produced by packages.core.features
  INGEST_PROTOCOL_VERSION wire protocol between collectors and POST /api/v1/sessions
"""

APP_VERSION = "1.3.0"
MODEL_VERSION = "v1.2.1-actor-inference"
FEATURE_SCHEMA_VERSION = "v1.2"
INGEST_PROTOCOL_VERSION = 2
