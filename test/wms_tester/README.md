# WMS/Tile Search Diagnostic Tool

This tool performs actual searches and image downloads to diagnose issues with:
- Collection filtering (mixing of different collections in search results)
- GSD consistency across tiles
- Image dimension consistency
- Tile spatial connectivity (gaps/overlaps)

## Usage

### Run all test cases:
```bash
python wms_diagnostic.py
```

### Run a specific test case:
```bash
python wms_diagnostic.py --test test_quickview_visual_thumb.json
```

### Specify custom directories:
```bash
python wms_diagnostic.py my_test_cases --output my_results
```

## Test Case Format

Test cases are JSON files in the `test_cases/` directory with the following structure:

```json
{
  "name": "Test Case Name",
  "collection_id": "quickview-visual-thumb",
  "center_lat": 16.46092468,
  "center_lon": 111.56210960,
  "aoi_size_km": 20,
  "contract_id": null
}
```

### Fields:

- **name** (required): Human-readable name for the test case
- **collection_id** (required): Satellogic collection ID to search
- **center_lat** (required): Center latitude for the AOI
- **center_lon** (required): Center longitude for the AOI
- **aoi_size_km** (optional): Size of the AOI in kilometers (default: 20)
- **contract_id** (optional): Satellogic contract ID (default: from env)

## Output

The tool generates:

1. **Console output** with detailed analysis
2. **Downloaded images** in `test_results/<test_case_name>/`
3. **JSON results file** with all findings in `test_results/results_<timestamp>.json`

## What it Checks

### Search Results Analysis
- Whether multiple collections appear in results (collection mixing bug)
- GSD range and consistency
- Number of items per collection

### Tile Connectivity Analysis
- Gaps between tiles that should be adjacent
- Overlaps between tiles
- Tile size consistency

### Image Analysis
- Downloads up to 10 sample images per test case
- Checks image dimensions (width x height)
- Detects dimension variations within a collection

## Example Test Cases

See `test_cases/` for examples:
- `test_quickview_visual_thumb.json` - QuickView Visual Thumb collection
- `test_quickview_visual.json` - QuickView Visual collection
- `test_l1d_sr.json` - L1D SR collection

## Adding New Test Cases

Create a new JSON file in `test_cases/` directory with your test parameters. You can:

1. Copy an existing test case and modify it
2. Test different collections
3. Test different geographic locations
4. Test different AOI sizes

## Common Issues Detected

- ⚠️ **Collection mixing**: Search returning items from multiple collections
- ⚠️ **GSD variation**: Significant GSD differences within a collection
- ⚠️ **Dimension mismatch**: Images with different sizes in the same collection
- ⚠️ **Tile gaps**: Non-contiguous spatial coverage
- ⚠️ **Size inconsistency**: Tiles with varying dimensions
