# MySim remote Unity integration

## Fast path selected2026-10-25

The requested pool target is190 workers, not a verified running count. The selected scope is assembled-track renders plus8 representative mesh spot checks per track, at1920x1080; it does not generate images for all98,572 meshes.

`execution-policy.json`, `fast_plan.py`, `chain_state.py`, `freeze_node.py`, `node.py`, `dispatch_node.py` and `unity-node.yml` implement the dependency-local path: CPU-only export → unique source validation → track-local assembly/render in one Editor → final build. Export does not reserve a Unity license. A ready track need not wait for unrelated tracks. Input packages are immutable HTTPS deliveries with SHA256 checks; no per-mesh API upload or status polling is used. Dependency package delivery URLs must be supplied by the verified collector/storage path before freezing dependent nodes.

The shared SQLite API governor counts all controller attempts, even conditional304requests, against a4000-request rolling-hour cap, with1-second pacing and1000requests of headroom under the user's5000limit. It honors GitHub reset/Retry-After headers, stops on errors, never rotates credentials to escape limits, and never automatically retries an uncertain dispatch. All controlling clients must use the same budget file; unrelated legacy API clients are not magically governed. The dispatcher refuses activation until the capacity snapshot confirms competing API actors have been reconciled/budgeted. No new polling daemon has been started.

Use a fresh verified capacity snapshot, actual Unity license entitlement and an immutable node tag before `dispatch_node.py --apply`. It defaults to a no-dispatch dry run. Pending/uncertain reservations survive restart; only a confirmed terminal job and verified receipt complete a node. Ready Unity validation/track finishes take priority over more CPU exports. Existing mesh jobs and their controller are untouched.

Track rendering requests a CPU software graphics device, not `-nographics`; the GameCI `enableGpu` option only enables graphics initialization here. No hardware GPU is attached/requested. The code explicitly rejects devices not identified as software rasterizers. The initial llvmpipe/OpenGL pilot remains unvalidated. Baseline/candidate pictures, blank-frame checks, original lighting state and dark/bright pixel statistics are collected. Source lights are preserved, not declared balanced. `shadowsBalanced` and gameplay acceptance remain false until actual review and driving tests pass.

For a raw timing scenario:98,572/190 is about519meshes/worker.10,30or60seconds per mesh correspond to1.44,4.32or8.65worker-parallel hours before transfer/import/assembly. The chosen track+spot-check scope renders far fewer images; its real estimate depends on track/camera counts and the first pilot. No scenario is a measured completion promise.

Built for the recovered project's exact `6000.3.26f1` version. The original project is read only during preparation. Unity import, validation, track edits and player builds run in disposable GitHub-hosted Linux jobs, never in the local Editor.

## Pipeline

1. A private, SHA256-pinned project snapshot supplies `Assets`, `Packages` and `ProjectSettings`, including original `.meta` files. No `Library`, credentials, `.git`, logs or local Unity license is packaged.
2. A complete intake manifest identifies each accepted candidate archive, its internal blend hash, exact source asset/hash, Unity mesh identity, source-relative coordinate conversion, original collision object, render/LOD objects and existing Unity material paths.
3. Unique shards fetch and verify candidate archives on remote CPU runners. Blender exports original corner UVs, normals, tangents and color to a binary float32 format. It splits large objects into bounded pieces without changing their positions or UV values. Blender auto-execution is disabled.
4. Unity creates separate `.asset` meshes directly; it never regenerates/repackages UV1 or relies on an FBX importer round trip. All original collision vertices/UVs and triangle counts must match the resolved Unity source. An explicit transform must pass this match; axis/unit guesses do not pass. Source names/fileIDs must resolve uniquely.
5. Each track runs in its own project copy. Existing render instances are mapped to verified candidates; material objects/ST, property blocks, lightmap indices and transforms remain on the original bindings. Driving colliders remain unchanged. Existing LOD group membership is remapped; standalone sources use explicitly supplied LOD thresholds. Skinned sources stop for dedicated rig-preserving handling.
6. Patched track prefabs keep the original GUID and original object/fileID inventory. Only the isolated runner copy is edited. Complete, hash-sealed track packages can then be imported into a final isolated project and built as a Linux player.

No compute success or structural report claims final artistic quality, correct lightmap-array appearance, GPU performance or playability. Those remain separate acceptance tests. No paid runners or GPU jobs are configured.

## Repository layout

Publish `Editor`, `tools`, `tests` and this document under `unity-pipeline/` in the pipeline repository. Publish `.github/workflows/*.yml` at the repository root. Third-party actions are pinned to resolved commits. Do not copy `validation/`, project snapshots, mesh archives or activation credentials into Git.

## Required CI configuration

These workflows do not launch simply because mesh compute is finished.

* `MYSIM_UNITY_LICENSE_SLOTS` repository variable: actual authorized concurrent CI license count. Default is no entitlement, not140. Start with1 for the first remote pilot. The Unity workflows share one global repository concurrency group to avoid parallel pipeline runs consuming the same slots.
* CI activation secrets supported by GameCI: your appropriate `UNITY_LICENSE` or `UNITY_SERIAL` plus `UNITY_EMAIL` and `UNITY_PASSWORD`, or `UNITY_LICENSING_SERVER`. Configure through GitHub Secrets. Never put credentials in a manifest or chat.
* `MYSIM_PROJECT_URL`: private HTTPS download for the final immutable project snapshot. Its SHA256 is supplied on dispatch.
* `MYSIM_CATALOG_PROJECT_URL`: optional small source-only snapshot URL for the initial inventory workflow.
* `MYSIM_UNITY_MANIFEST_URL`: HTTPS intake manifest URL; dispatch pins its SHA256.

Licensing setup is not a claim of entitlement. The first remote run must actually activate and import successfully. A GitHub account or free runner is not a Unity license. Follow your applicable Unity CI terms.

## Initial remote pilot

The source catalogue can be prepared before the final20 mesh results arrive. `pack_project.py` can produce a small inventory-only snapshot containing selected original FBXs and their unchanged `.meta` files, plus Packages/ProjectSettings:

```powershell
python tools/pack_project.py --project D:/MySim-recovered/full-game-build/project --output D:/MySim-processed/unity-intake/catalogue.tar.gz --catalog-asset Assets/RealRacing/Source/spa/processed/high/spa.fbx
```

This performs file packaging only. It does not launch Unity or upload anything. Run `unity-source-inventory.yml` remotely after activation and private snapshot delivery are configured. Its catalogue provides exact source names/GUIDs/fileIDs; coordinate conversions are accepted only after comparing the original collision with that source. Catalogue snapshots are not complete build projects.

For one representative finished mesh, provide source bindings and a candidate index, then join them:

```text
python tools/make_manifest.py --bindings bindings.json --candidates candidates.jsonl --expected-count 1 --output manifest.json
```

For the final whole-inventory manifest, use the actual exact expected unique count (98,572), not a padding count. The input is rejected for duplicate IDs, missing candidates, duplicate source bindings, unknown tracks or missing LOD/source transforms. `make_manifest.py` does not invent bindings or silently select a different candidate revision.

The integration workflow starts with1 shard/1 authorized Unity worker and player build disabled. After actual source mapping, UV/page, material, prefab identity, collision, import memory and images are verified on the representative track, increase distinct shards within measured runtime/memory/disk and licensing limits. No140-worker Unity promise is made.

## Input contract

`bindings.json`: `tracks` (each `id`, `sourcePrefab`, `sourcePrefabSha256`), `buildScenes`, and `entries` with `id`, `sourceAsset`, `sourceSha256`, `sourceMesh`, optional exact `sourceFileId` string, row-major affine16-value `sourceToUnity`, `trackIds`, `materialPaths` in candidate slot order, `lodHeights`, `collisionObject`, and `parts` (`object`, `lod`, starting at0).

Each `candidates.jsonl` row pins the same `id`, `archiveUrl`, `archiveSha256`, `blendMember`, `blendSha256` and `reportMember`. The archive must contain `SHA256SUMS.json` and a passed full-source worker record pinning this blend. Partial component prototypes are not accepted as full-source assets. If object roles or a source matrix are not established, the input is not ready; inspect the original/candidate data rather than guessing them.

Use full final-parent assemblies for compound sources, with all render pieces declared. Original collision is exchanged only for source comparison; it never replaces the original Unity collider. Existing material/ST and encoded UV1 pages stay intact. Imported objects use the source local space verified by the collision correspondence.

## Resource limits and results

Whole job300min, compute cutoff270min, Unity/Blender main process12GiB, published shard/track/build output1GiB. A host watchdog includes the Editor's initial project import in monitoring. Large objects are split in transport, not simplified. Initial project snapshot limits are6GiB compressed/10GiB expanded and a disk headroom check; if the project exceeds these, produce a measured dependency-closed track snapshot, rather than silently dropping files or weakening limits. A full player exceeding1GiB needs a separately validated streaming/package split, not an unguarded upload.

Passing reports and package files must all appear in `SHA256SUMS.json`. Every expected unique source and assembled track must be present exactly as declared before the next stage. The workflow retains failed diagnostics and never labels missing/queued work completed. Raw project snapshots are never uploaded as public CI artifacts by these workflows.

## Verification status

Python protocol tests cover encoded-UV float32 identity, malformed matrices/LODs/indices, path traversal, package injection, exact coverage, duplicate records, missing packages and licensing/work sharding. `compile_editor_check.py` compiles against installed Unity reference assemblies without starting Unity or touching project assets. A compile against available6000.6.7 reference DLLs is a syntax/API check only; it is not a6000.3.26 runtime pass. No remote Unity import/build is claimed until a properly licensed pilot actually runs.

References: [Unity command-line automation](https://docs.unity.cn/Manual/EditorCommandLineArguments.html), [Unity source GUID/fileID API](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/AssetDatabase.TryGetGUIDAndLocalFileIdentifier.html), [read-only Editor mesh access](https://docs.unity3d.com/6000.0/Documentation/ScriptReference/MeshUtility.AcquireReadOnlyMeshData.html), [GameCI activation](https://game.ci/docs/github/activation/).
