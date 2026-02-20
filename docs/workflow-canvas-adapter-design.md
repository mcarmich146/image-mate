# Workflow Canvas Adapters Design

## Problem
Workflow functions are easier to maintain when they implement one level of logic (atomic or aggregate). Source nodes can emit grouped inputs (`single`, `stack`, and future bundle modes), which creates shape mismatch at connect time.

Without adapters, functions either:
- duplicate logic to handle every grouping type, or
- reject useful connections that could be transformed safely.

## Design Goals
- Keep function logic reusable and focused.
- Make grouping conversion explicit in the graph.
- Preserve user trust by keeping auto-conversions visible.
- Introduce adapters incrementally, starting with one low-risk case.

## Shape Model
Canvas/runtime shape vocabulary:
- `image`: one raster artifact.
- `stack`: ordered list of raster artifacts.
- `mosaic_bundle` (future): grouped rasters representing spatial tiles.
- `multi_temporal_stacks` (future): set of stacks.

Function behavior classes:
- `atomic`: acts on one image at a time.
- `aggregate`: requires a grouped input (example: temporal video).

## Adapter Model
An adapter is a node that transforms how grouped artifacts flow between nodes.

Current adapter id:
- `for_each_image_in_stack`

Meaning:
- receives stack artifacts
- applies atomic semantics per image
- emits a stack with the same image count and ordering

UI label:
- `Adapter For Each Image in Stack -> <Function Name>`

## UX Behavior
When user connects:
- source node in `stack` mode
- to a `clip_to_aoi` function node

Then canvas auto-inserts a visible adapter node:
- the target `clip_to_aoi` function node is replaced by an adapter wrapper node
- wrapper keeps the embedded `clip_to_aoi` payload internally
- resulting graph segment is `source -> adapter` (adapter now acts as clip function endpoint)

Notes:
- adapter node is visible and serialized in workflow JSON.
- double-clicking the adapter opens the embedded function config dialog.

## Runtime Behavior
Execution supports `adapter` node type.

For `for_each_image_in_stack`:
- adapter can execute an embedded function payload.
- current embedded function support: `clip_to_aoi`.
- backward compatibility: legacy pass-through adapter payloads still run.

## JSON Representation
Node payload example:

```json
{
  "type": "adapter",
  "label": "Adapter For Each Image in Stack -> Clip to AOI",
  "payload": {
    "adapter_id": "for_each_image_in_stack",
    "adapter_name": "For Each Image in Stack",
    "adapted_function_id": "clip_to_aoi",
    "adapted_function_name": "Clip to AOI",
    "adapted_function_payload": {
      "output_path": "C:/tmp/clip_output.tif",
      "aoi_source_type": "project_layer"
    },
    "auto_inserted": true
  }
}
```

## Output Naming (Lifted Single -> Stack)
When an atomic function is lifted over a stack, output paths are decided as:
- if only one item: use `output_path` exactly.
- if multiple items and no template tokens: suffix as `_<index_03>` (example: `clip_001.tif`, `clip_002.tif`).
- if template tokens are present in `output_path`, render per artifact:
  - `{index}`, `{index_03}`, `{item_id}`, `{collection_date}`, `{collection_datetime}`, `{logical_source_key}`
- duplicate rendered names are auto-deduplicated with deterministic numeric suffixes.

## Current Phase Scope
Implemented now:
- visible `adapter` node type in canvas
- auto-insert for `stack source -> clip_to_aoi`
- runtime support for `adapter` execution (`for_each_image_in_stack`)

Not implemented yet:
- adapters for future shapes (`mosaic_bundle`, `multi_temporal_stacks`)
- aggregate adapters (explode/regroup/mosaic merge)
- generalized shape contract registry

## Next Steps
1. Add adapter contract metadata to function specs (`accepted_shapes`, `liftable`).
2. Expand auto-insert matrix for additional safe transforms.
3. Add adapter-specific validation messaging in canvas before execution.
4. Introduce aggregate adapters (`explode bundle`, `regroup stack`) when new source modes are enabled.
