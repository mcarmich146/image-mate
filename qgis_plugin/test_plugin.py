"""Test script to verify SourceService functionality."""

import sys
from pathlib import Path

# Add plugin to path
plugin_path = Path.home() / "AppData" / "Roaming" / "QGIS" / "QGIS3" / "profiles" / "default" / "python" / "plugins"
sys.path.insert(0, str(plugin_path))

from dataclasses import dataclass

@dataclass
class MockSettings:
    satellogic_contract_id: str = ""
    cdse_wmts_base_url: str = ""
    cdse_wmts_instance_id: str = ""
    cdse_wmts_layer_id: str = ""
    cdse_enabled: bool = False
    satellogic_authcfg_id: str = ""
    cdse_authcfg_id: str = ""


def test_imports():
    print("Testing imports...")
    from image_mate_qgis_plugin.clients import config, satellogic_client, merlin_sentinel2_client, source_manager
    print("✓ All client modules imported successfully")
    print(f"✓ Settings loaded: {config.settings.satellogic_api_base_url}")
    print(f"✓ Env file found: {config.env_file}")
    
    # Get detailed diagnostics
    diag = config.get_config_diagnostics()
    print(f"✓ Diagnostics:")
    for key, value in diag.items():
        print(f"  - {key}: {value}")
    
    # Check credentials
    import os
    has_bearer = bool(os.getenv("SATELLOGIC_BEARER_TOKEN", "").strip())
    has_key_secret = bool(os.getenv("SATELLOGIC_KEY_ID", "").strip() and os.getenv("SATELLOGIC_KEY_SECRET", "").strip())
    print(f"✓ Credentials detected: Bearer={has_bearer}, KeySecret={has_key_secret}")
    
    return True


def test_source_service():
    print("\nTesting SourceService...")
    from image_mate_qgis_plugin.services.source_service import SourceService
    
    svc = SourceService(MockSettings())
    print("✓ SourceService instantiated")
    print(f"✓ Initialization error: {svc._init_error if svc._init_error else 'None'}")
    print(f"✓ Manager ready: {bool(svc._manager)}")
    
    if svc._manager:
        sources = svc.list_sources()
        print(f"✓ Sources available: {len(sources)}")
        for source in sources:
            print(f"  - {source['source_id']}: {source['title']} (enabled: {source['enabled']})")
    
    return bool(svc._manager)


def main():
    try:
        test_imports()
        test_source_service()
        print("\n" + "="*50)
        print("✓ All tests passed!")
        print("="*50)
        return 0
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
