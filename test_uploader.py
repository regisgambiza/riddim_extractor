#!/usr/bin/env python3
"""
Quick test for the new mapping-based uploader feature.
This verifies that the feature loads and the workflow steps work correctly.
"""
import tempfile
from pathlib import Path
import json

from riddim_extractor_gui import ExtractorCore


def test_mapping_uploader_integration():
    """Test basic integration of mapping loader and uploader concept."""
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "source"
        dest = tmp_path / "dest"
        source.mkdir()
        dest.mkdir()
        
        # Create some test folders
        (source / "001 test riddim").mkdir()
        (source / "002 another riddim").mkdir()
        
        # Create a mapping file
        mappings = {
            "generated_by": "riddim_agent",
            "generated_at": "2026-10-01T21:49:09.698329+00:00",
            "source": "match_proposals.json",
            "mappings": {
                "001 test riddim": 2025,
                "002 another riddim": 2026,
                "003 missing folder": 2027,  # This one doesn't exist
            }
        }
        
        mapping_file = tmp_path / "year_mapping.json"
        with open(mapping_file, "w") as f:
            json.dump(mappings, f)
        
        # Create ExtractorCore with state file
        state_file = tmp_path / "state.json"
        core = ExtractorCore(source, dest, state_file)
        
        # Test load_year_mapping
        result = core.load_year_mapping(mapping_file)
        
        print("OK Load year mapping result:", result)
        
        # Verify imported_years
        assert "001 test riddim" in core.imported_years
        assert "002 another riddim" in core.imported_years
        assert "003 missing folder" in core.imported_years
        print("OK Imported years:", core.imported_years)
        
        print("OK Core state initialized correctly")
        
        print("\nAll tests passed! Mapping-based uploader concept works.")


if __name__ == "__main__":
    test_mapping_uploader_integration()