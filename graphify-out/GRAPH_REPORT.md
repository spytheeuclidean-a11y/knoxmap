# Graph Report - KnoxMap  (2026-10-13)

## Corpus Check
- Large corpus: 392 files · ~625,435 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder.

## Summary
- 3571 nodes · 8032 edges · 199 communities (152 shown, 47 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 325 edges (avg confidence: 0.88)
- Token cost: 700 input · 350 output

## Community Hubs (Navigation)
- Multipolygon Rings & Selftest Geometry
- OSM Road Classification
- Build Pipeline Core
- Builder API Presets
- OSM Query & Area Fetch
- Interior Room Layout
- Building Room Placement
- Building Tile Composition
- Tile Blend Layers
- Web App API Endpoints
- PZ Map Colors & Bitmaps
- Places & Landmarks
- Sketch Frontend JS
- Updater & Staging
- Design & Sketch API
- Layout Kind Assignment
- Knoxpaths & Tile Media
- Bathroom Furnishing
- Reports & Memory Errors
- Building Style & Materials
- WorldEd Experiments
- Octilinear Settings Tests
- WorldEd CLI Patch & Bench
- Presence & Pipe IPC
- Mod Map Install
- Notable Buildings & Build Entry
- Apartment Room Layout
- Building Plan & Railings
- Setup Script Utils
- Headercheck & Room Tables
- Building-Kind Tests
- Windows Process Primitives
- Batch Building Layout Runner
- Compile State Tracking
- Blends & Rules Loading
- Kind Assignment & Atriums
- OSM Feature Cache & Sea
- Overture Data Merge
- Leaflet Lasso Frontend
- Builder Autofill API
- Buildings API & Workers
- Zones Config
- Qt Runtime Setup
- Rust Cell Export Format
- Structure Arches & Columns
- Picture Rendering
- Preset Library
- WorldEd Project Repair
- Octilinear Road Geometry
- Designer Autofill
- Facade & Entrances
- Erika Tile Catalog
- Door Fronts & Painting
- Bounds & Bitmap Area Helpers
- BX File Blocks
- OSM Feature Geometry
- Fence Building
- Shop Floor & Street Walls
- Petrol Station Forecourt
- World File Writer
- Map Report API
- Subprocess Runner
- Grid Angle & Bbox
- Drawing Board UI
- Map Listing API
- Map Projector
- Regression Fixture Checks
- Bridges & Mend Fragments
- Map Origin & Binary Read
- Worldmap Binary IO
- Road Hierarchy Tests
- Board Frontend API Client
- Surroundings Classification
- Roof & Ceiling Tiles
- Launcher & Port Control
- Catalog & Window Cutouts
- Drawing Sheet Design Tests
- Changelog Docs
- Contributing & Legal Docs
- Rust Main & Cell
- Path Chain Joins
- Config & Atomic Write
- Rust BMP Encoding
- Rust Pack Encoding
- Workshop Art Generator
- Storey Count Pools
- NYC Midtown Terrain Docs
- Footprint Geometry
- Prop Placement
- Rust Cell Type
- Rust ChunkData Parse
- Preset Frontend Settings
- Batch Compile Runner
- CI Workflow & Release Docs
- Language Files & Sketch Docs
- Sheet House Floor Plan Images
- Picture Pixel IO
- Row Unit Footprints
- Box Clearing & Cost
- Cell Source Writer
- Frontend Map & Preset UI
- Minified JS Helpers
- Blend Tests
- Sketch Tests
- Win32 Type Bindings
- Apartment Sheet Images
- Regression Optional Checks
- Region Detection
- Zone Editor Frontend
- Leaflet Draw Vendor JS
- Design Build Tests
- Pack Reader
- Workshop Check
- Rust Compile & Image
- Render Settings Tests
- Gun Placement
- Compile Poll Frontend
- Building Alignment Tests
- Palette Tests
- KnoxMap Cover & Wordmark Images
- App Screenshot Images
- Interior Cutaway Images
- Building Mask Preview
- Room Overlap Tests
- Picture Scale Tests
- Focal Room Furnishing
- Terrain Source Tests
- Hidden Desktop Process
- Lot Render Tool
- Road Details Painting
- Minified JS Helpers
- Minified JS Helpers
- Preset Naming Tests
- Preset Choice Tests
- Batch Throttle
- Compile Failure Checks
- Floorplan Preview Tool
- Rooftop & Cutaway Images
- Stop Map Tool
- Area Spatial Index
- Dwelling Checks
- Room Color Mix
- Home Door Reachability
- Loot Reset Lua
- Fitting Choice
- Editable Tags Frontend
- Minified JS Helpers
- Sheet Design Tests
- Render Ground Rules
- Wall Corner Checks
- KnoxMap Logo Images
- Ingame Cutaway Images
- Street Furniture Painting
- Building Storey & Materials
- Setup Logging
- Rust Byte Reader
- Tower Preview Tool
- Bundle Extraction
- Fixture Docs
- Project Repair
- Edit Cleaning Tests
- Bitmap Scale Helpers
- Workshop Upload Checks
- Tower & Skyscraper Images
- Apartment Layout Images
- Roads Tiles Images
- Spawn Comparison Images
- Car Park Stalls
- Footprint Cut
- Business Layout Tests
- Hand-Drawn Buildings Tests
- Sheet Fill Tests
- Street Angle Checks
- Compile Cell Count
- Linux Docs
- Overpass Docs
- Times Square Render Images
- Monument & Tower Kinds
- Lua Guncache
- Wine Tool Runner
- Logo Concept Images
- Minified JS Helpers
- Bathroom Sink Tests
- Road Furniture Tests
- Qt RPATH Checks
- Window Relaunch
- Height Profile
- Ground Share Checks
- Mapped Rooms Checks
- Cross-Site Checks
- Checks Helper
- Setup Command
- fx.js
- i18n.js
- Launcher Build Script
- Rooftop Vents Image
- knoxlots

## God Nodes (most connected - your core abstractions)
1. `main()` - 94 edges
2. `Settings` - 93 edges
3. `build()` - 89 edges
4. `OSMFeature` - 74 edges
5. `render()` - 55 edges
6. `Plan` - 52 edges
7. `build_plan()` - 45 edges
8. `generate()` - 40 edges
9. `Projector` - 32 edges
10. `build_building()` - 32 edges

## Surprising Connections (you probably didn't know these)
- `WorldEd output as reference fixtures` --semantically_similar_to--> `tbx and pzw file format rules`  [INFERRED] [semantically similar]
  rust/knoxlots/fixtures/README.md → KNOXBUILD.md
- `generate()` --uses--> `Settings`  [INFERRED]
  app.py → knoxbuild/settings.py
- `api_buildings()` --uses--> `Settings`  [INFERRED]
  app.py → knoxbuild/settings.py
- `api_zombies()` --uses--> `Settings`  [INFERRED]
  app.py → knoxbuild/settings.py
- `_save_settings()` --uses--> `Settings`  [INFERRED]
  app.py → knoxbuild/settings.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **knoxlots clean-room compiler pipeline** — rust_knoxlots_readme, rust_knoxlots_source_format, rust_knoxlots_fixtures_readme, rust_knoxlots_experiments_blank_chunkdata_test, _github_workflows_knoxlots [INFERRED 0.85]
- **Licence zones of the repository** — licenses, license_mit, licenses_knoxify_no_license, licenses_gpl_worlded, docs_legal [INFERRED 0.85]
- **Map compile to install flow** — tutorial_four_buttons, templates_index_pipeline, readme_quick_start, changelog_compile_batches, knoxbuild_compile_batches, worlded_patch_cli [INFERRED 0.75]
- **KnoxMap brand identity lockup** — branding_cover_knoxmap_wordmark, branding_cover_map_pin_icon, branding_cover_tagline [INFERRED 0.75]
- **KnoxMap logo lockup (pin, wordmark, tagline)** — branding_cover_map_pin_mark, branding_cover_wordmark, branding_cover_tagline [INFERRED 0.85]
- **Map generation flow: draw area, configure settings, generate** — docs_images_app_drawing_tools, docs_images_app_area_panel, docs_images_app_settings_panel, docs_images_app_generate_map_button [INFERRED 0.85]
- **Interior rooms of the cutaway building** — docs_images_ingame_cutaway_bathroom, docs_images_ingame_cutaway_bedroom_suite, docs_images_ingame_cutaway_utility_room [INFERRED 0.75]
- **Fenced backyard layout** — docs_images_ingame_houses_wooden_privacy_fence, docs_images_ingame_houses_white_picket_fence, docs_images_ingame_houses_sandbox [INFERRED 0.75]
- **Cutaway buildings sharing interior rendering** — docs_images_ingame_rooftops_west_cutaway_building, docs_images_ingame_rooftops_east_cutaway_building, docs_images_ingame_rooftops_south_cutaway_building, docs_images_ingame_rooftops_cutaway_interior_pattern [INFERRED 0.75]
- **Tower types composing the city block** — docs_images_ingame_skyscrapers_glass_tower, docs_images_ingame_skyscrapers_brick_tower, docs_images_ingame_skyscrapers_office_interior [INFERRED 0.75]
- **Midtown theatre district** — docs_images_nyc_midtown_theatre_district, docs_images_nyc_midtown_new_amsterdam_theatre, docs_images_nyc_midtown_lyric_theatre, docs_images_nyc_midtown_times_square, docs_images_nyc_midtown_broadway [INFERRED 0.75]
- **Apartment floors and roof of one building** — docs_images_real_apartment_floor_0, docs_images_real_apartment_floor_1, docs_images_real_apartment_roof [INFERRED 0.75]
- **Stacked floor plans and roof of the apartment building** — docs_images_sheet_apartment_floor_0, docs_images_sheet_apartment_floor_1, docs_images_sheet_apartment_floor_2, docs_images_sheet_apartment_roof [EXTRACTED 1.00]
- **House sheet levels (floors and roof)** — docs_images_sheet_house_floor_0, docs_images_sheet_house_floor_1, docs_images_sheet_house_roof [EXTRACTED 1.00]
- **KnoxMap logo mark composition** — static_logo_background, static_logo_isometric_floor_tile, static_logo_map_pin [EXTRACTED 1.00]

## Communities (199 total, 47 thin omitted)

### Community 0 - "Multipolygon Rings & Selftest Geometry"
Cohesion: 0.04
Nodes (35): assemble_rings(), box(), check_box_any(), check_config_file(), check_degenerate_footprints(), check_facing(), check_flat_selection(), check_health() (+27 more)

### Community 1 - "OSM Road Classification"
Cohesion: 0.06
Nodes (38): classify(), road_hierarchy(), _areas_geojson(), _box_any(), _build_preview(), _build_spawn_map(), _buildings_geojson(), _clear_building_vegetation() (+30 more)

### Community 2 - "Build Pipeline Core"
Cohesion: 0.05
Nodes (31): build(), laid_out(), make_spawn_map(), say(), _business_kind(), classify_building(), _code_fingerprint(), _detect_zones() (+23 more)

### Community 3 - "Builder API Presets"
Cohesion: 0.05
Nodes (35): api_builder(), api_builder_kind(), api_builder_save(), api_builder_use(), api_building_preset(), api_building_presets(), api_client_error(), api_compile() (+27 more)

### Community 4 - "OSM Query & Area Fetch"
Cohesion: 0.05
Nodes (33): _area_km2(), _ask(), _build_query(), check_endpoints(), one(), _config_list(), _endpoint_order(), _error_text() (+25 more)

### Community 5 - "Interior Room Layout"
Cohesion: 0.06
Nodes (26): bed_against_wall(), _cells(), eatery_style(), _fits(), Frame, _front_side(), furnish_dining(), furnish_office() (+18 more)

### Community 6 - "Building Room Placement"
Cohesion: 0.07
Nodes (18): building_rooms(), cell_tables(), placed_rooms(), room_rects(), flat_squares(), roof_squares(), upper_level(), building() (+10 more)

### Community 7 - "Building Tile Composition"
Cohesion: 0.10
Nodes (18): Building, compose_lots(), _entry(), Floor, level_tiles(), parse_tbx(), _tile_grid(), tile_name() (+10 more)

### Community 8 - "Tile Blend Layers"
Cohesion: 0.08
Nodes (21): Blend, blend_layers(), look(), see(), _members(), _neighbour(), parse_blends(), _blocks() (+13 more)

### Community 9 - "Web App API Endpoints"
Cohesion: 0.06
Nodes (26): api_edits(), api_features(), api_health(), api_language(), api_languages(), api_setup_status(), api_zone_settings(), _edits_path() (+18 more)

### Community 10 - "PZ Map Colors & Bitmaps"
Cohesion: 0.10
Nodes (14): _bmp_header(), cell_hashes(), _fast(), read_gray(), read_rgb_rows(), same_colour(), build_spawn_map(), _ground_shares() (+6 more)

### Community 11 - "Places & Landmarks"
Cohesion: 0.06
Nodes (16): _build_query(), landmarks(), _notability(), _outline(), _parse(), search(), _throttle(), Base (+8 more)

### Community 12 - "Sketch Frontend JS"
Cohesion: 0.05
Nodes (33): addSketchShape(), bdDraw(), bdHistory, bdMetaFor, bdRemember(), drawControl, drawnItems, EDIT_PICKED (+25 more)

### Community 13 - "Updater & Staging"
Cohesion: 0.11
Nodes (27): apply_staged(), _asset(), check(), choose(), _clear_aside(), current_version(), _digest(), enabled() (+19 more)

### Community 14 - "Design & Sketch API"
Cohesion: 0.08
Nodes (25): api_design(), api_sketch(), api_sketch_palette(), _bbox_area_km2(), _cos_lat(), _design_path(), generate(), _load_design() (+17 more)

### Community 15 - "Layout Kind Assignment"
Cohesion: 0.07
Nodes (21): _assign_flat_kinds(), _assign_house_kinds(), _blocks(), _circulation(), _clear_the_way(), _contiguous(), _graph_distance(), _house_bedrooms_on_floor() (+13 more)

### Community 16 - "Knoxpaths & Tile Media"
Cohesion: 0.11
Nodes (22): _children(), chosen_steam_folders(), erikas_tiles_media(), erikas_tiles_ready(), _exists(), _find_steam_libraries(), _first(), is_build42() (+14 more)

### Community 17 - "Bathroom Furnishing"
Cohesion: 0.09
Nodes (24): _bath_mat_spot(), _bathroom_wishlist(), _cells_for(), _clear_for_stairs(), _counter_runs(), _erika_ready(), _facing(), _furnish() (+16 more)

### Community 18 - "Reports & Memory Errors"
Cohesion: 0.07
Nodes (19): api_report(), index(), _too_big_for_memory(), error_id(), explain_exit(), _install_hooks(), _memory(), memory_status() (+11 more)

### Community 19 - "Building Style & Materials"
Cohesion: 0.06
Nodes (9): pick_style(), _wall_pool(), wall_variants(), _year(), cn_house_styles(), BuildingProfileTests, ChineseStyles, RoomFurnitureLayouts (+1 more)

### Community 20 - "WorldEd Experiments"
Cohesion: 0.09
Nodes (19): summarise(), main(), measure_cell(), read_header(), read_squares(), _string(), summary(), canonicaliser() (+11 more)

### Community 21 - "Octilinear Settings Tests"
Cohesion: 0.10
Nodes (10): Settings, OctilinearRoadDefaults, SettingsArchStyle, AcrossTheWholeMap, Asking, Cleaning, ForTheWindow, Projector (+2 more)

### Community 22 - "WorldEd CLI Patch & Bench"
Cohesion: 0.09
Nodes (16): Patched WorldEd CLI generate-map switch, main(), _copy(), _edit(), _hashes(), main(), main(), generate-map headless switch patch (+8 more)

### Community 23 - "Presence & Pipe IPC"
Cohesion: 0.08
Nodes (8): app_id(), enabled(), idle(), large_image(), _Pipe, _pipe_paths(), Presence, stage()

### Community 24 - "Mod Map Install"
Cohesion: 0.10
Nodes (18): _clear_folder(), collect(), default_mods_dir(), knoxpaths_module(), _lua_string(), main(), package(), _spawn_tiles() (+10 more)

### Community 25 - "Notable Buildings & Build Entry"
Cohesion: 0.09
Nodes (6): is_notable(), BuildingProfile, _clamp(), FurnishedRoomWalkability, NotableBuildings, RoofLayouts

### Community 26 - "Apartment Room Layout"
Cohesion: 0.08
Nodes (20): _along(), _apartment_rooms(), _corridor_axis(), _door_cost(), _door_spot(), _doors(), start_room(), _flat_frontage() (+12 more)

### Community 27 - "Building Plan & Railings"
Cohesion: 0.07
Nodes (13): build_building(), _clear_railing_at(), _largest_rectangle(), _pick_core(), _pick_corridor(), _pick_shaft(), _place_escalators(), roof_rects() (+5 more)

### Community 28 - "Setup Script Utils"
Cohesion: 0.17
Nodes (18): add_erikas_tiles(), _ask(), choose_steam_folders(), configure_tools(), download(), ensure_mapping_tools(), ensure_patched_cli(), find_game() (+10 more)

### Community 29 - "Headercheck & Room Tables"
Cohesion: 0.09
Nodes (11): main(), read_tilesets_txt(), is_words(), main(), page_strings(), script_strings(), crop_tile(), main() (+3 more)

### Community 30 - "Building-Kind Tests"
Cohesion: 0.08
Nodes (4): ForAKindOfBuilding, Reading, tbx(), TheLibrary

### Community 31 - "Windows Process Primitives"
Cohesion: 0.10
Nodes (15): assign_converted_maps(), fill(), clear_stale(), compile_map(), default_workers(), _free_memory_gb(), main(), _only_one() (+7 more)

### Community 32 - "Batch Building Layout Runner"
Cohesion: 0.09
Nodes (15): _make_all(), run_here(), _make_one(), Building, _add(), _attrs(), _peak_depth(), render_tbx() (+7 more)

### Community 33 - "Compile State Tracking"
Cohesion: 0.12
Nodes (17): batch_needs_work(), discard(), fingerprints(), tbx(), forget(), _global_fingerprint(), _grow(), _key() (+9 more)

### Community 34 - "Blends & Rules Loading"
Cohesion: 0.14
Nodes (14): load_blends(), load_rules(), stack_order(), main(), _free_gb(), main(), make_map_source(), merge_stack() (+6 more)

### Community 35 - "Kind Assignment & Atriums"
Cohesion: 0.09
Nodes (12): _assign_kinds(), _atrium_railings(), build_plan(), _by_expected_size(), _clear_concourse(), _open_shopfronts(), _room_cap(), _stair_foot() (+4 more)

### Community 36 - "OSM Feature Cache & Sea"
Cohesion: 0.10
Nodes (15): cache_path(), load_cache(), sea_polygons(), shape_px(), _points_of_use(), _clean(), _line(), _lua_string() (+7 more)

### Community 37 - "Overture Data Merge"
Cohesion: 0.13
Nodes (15): add_missing(), _area_m2(), available(), cache_path(), fetch(), run(), load_cache(), only_missing() (+7 more)

### Community 38 - "Leaflet Lasso Frontend"
Cohesion: 0.08
Nodes (8): LassoControl, a(), Ci(), ei(), ii(), l(), ri(), x()

### Community 39 - "Builder Autofill API"
Cohesion: 0.08
Nodes (15): api_builder_autofill(), api_builder_design(), api_builder_preview(), _api_error(), api_preset_delete(), api_presets(), api_update_restart(), api_versions() (+7 more)

### Community 40 - "Buildings API & Workers"
Cohesion: 0.09
Nodes (15): api_buildings(), say(), worker(), api_map(), api_zombies(), _done_stopping(), _progress(), _load_settings() (+7 more)

### Community 41 - "Zones Config"
Cohesion: 0.09
Nodes (5): clean(), load(), overridable(), save(), Zoning

### Community 42 - "Qt Runtime Setup"
Cohesion: 0.10
Nodes (13): _carries_qt(), command_for(), compiler_trouble(), force_bundled_qt(), _force_rpath(), _probe_compiler(), qt_trouble(), through_wine() (+5 more)

### Community 43 - "Rust Cell Export Format"
Cohesion: 0.11
Nodes (15): export_cell(), CHUNK_VALUES, Header, MAGIC, Room, get_str(), KCell, MAGIC (+7 more)

### Community 44 - "Structure Arches & Columns"
Cohesion: 0.21
Nodes (16): _arch(), _cells(), _column(), _fountain(), _lay_run(), Plan, plan_monuments(), _posts() (+8 more)

### Community 45 - "Picture Rendering"
Cohesion: 0.14
Nodes (10): compiled(), map_size(), _on_background(), picture(), pictures_of(), _pixels(), _scale_for(), _trim() (+2 more)

### Community 46 - "Preset Library"
Cohesion: 0.16
Nodes (13): folder(), kinds(), library(), manifest(), measure(), read(), remove(), safe_name() (+5 more)

### Community 47 - "WorldEd Project Repair"
Cohesion: 0.13
Nodes (3): world(), load(), world()

### Community 48 - "Octilinear Road Geometry"
Cohesion: 0.12
Nodes (11): _blur(), _dist_to_line(), _key(), _legs(), _round_together(), find(), shared(), _simplify_idx() (+3 more)

### Community 49 - "Designer Autofill"
Cohesion: 0.13
Nodes (13): autofill(), blank(), clean(), design_path(), drop_design(), _int(), keep(), load_design() (+5 more)

### Community 50 - "Facade & Entrances"
Cohesion: 0.11
Nodes (10): _bays(), _facade_runs(), _front_side(), _place_windows(), bays_for(), _room_edges(), audit(), irregular_mask() (+2 more)

### Community 51 - "Erika Tile Catalog"
Cohesion: 0.13
Nodes (15): _blank(), erika_roles(), main(), bt_entry(), bt_lookup(), caps_for(), pick(), roof() (+7 more)

### Community 52 - "Door Fronts & Painting"
Cohesion: 0.11
Nodes (13): paint(), door_fronts(), _outside_doors(), paint_paths(), at(), free(), match(), paint() (+5 more)

### Community 53 - "Bounds & Bitmap Area Helpers"
Cohesion: 0.13
Nodes (23): bboxAreaKm2(), bitmapFor(), boundsAround(), boundsForResult(), clearBboxFields(), currentPortablePreset(), fixScaleField(), haversineKm() (+15 more)

### Community 54 - "BX File Blocks"
Cohesion: 0.13
Nodes (7): make(), make_tbx(), grid_of(), main(), check(), _collect(), main()

### Community 55 - "OSM Feature Geometry"
Cohesion: 0.16
Nodes (6): OSMFeature, box(), line(), Applying, ForTheWindow, town()

### Community 56 - "Fence Building"
Cohesion: 0.13
Nodes (8): build_fences(), _fenced_sites(), _grid_path(), render_fence_tbx(), style_for(), _tarmac_mask(), _tile(), FenceCollisionTests

### Community 57 - "Shop Floor & Street Walls"
Cohesion: 0.10
Nodes (11): _assign_shop_floor(), street_wall(), _back_door(), _entrance_priority(), _entrance_wall(), _exterior_door(), _more_ways_in(), _outside_runs() (+3 more)

### Community 58 - "Petrol Station Forecourt"
Cohesion: 0.11
Nodes (6): _forecourt(), place_pumps(), build_structures(), pack_loose(), render_tiles_tbx(), Placement

### Community 59 - "World File Writer"
Cohesion: 0.11
Nodes (9): _installed_boxes(), origin(), render_pzw(), cell_map(), _tool_path(), Zone, check_porch_lights(), check_portable() (+1 more)

### Community 60 - "Map Report API"
Cohesion: 0.10
Nodes (13): api_open_logs(), api_preset_export(), api_preset_validate(), api_report_save(), _clean_shape(), _count_points(), walk(), _normalise_bbox() (+5 more)

### Community 61 - "Subprocess Runner"
Cohesion: 0.16
Nodes (7): _hashes(), main(), knoxlots_exe(), _hashes(), main(), main(), peak_memory_mib()

### Community 62 - "Grid Angle & Bbox"
Cohesion: 0.15
Nodes (8): cover_bbox(), district_a(), district_b(), grid(), ll(), seg(), TwoDistricts, Uniform

### Community 63 - "Drawing Board UI"
Cohesion: 0.19
Nodes (21): boardAdd(), boardDesign(), boardDrawSheet(), boardFit(), boardLoadDesign(), boardNote(), boardOpen(), boardPaletteInto() (+13 more)

### Community 64 - "Map Listing API"
Cohesion: 0.17
Nodes (10): api_maps(), _map_summary(), done(), made_with(), needs(), _parse(), _path(), read() (+2 more)

### Community 65 - "Map Projector"
Cohesion: 0.11
Nodes (6): _ceil_to(), _paint_multipolygon(), _places(), Projector, check_giant_outline(), check_odd_tags()

### Community 66 - "Regression Fixture Checks"
Cohesion: 0.17
Nodes (9): set_origin(), RegressionMapTests, compare(), compiled_hashes(), main(), run_case(), scenario_features(), add() (+1 more)

### Community 67 - "Bridges & Mend Fragments"
Cohesion: 0.15
Nodes (11): _boundary_edges(), _bridge_core(), _carve_shaft(), _mend_fragments(), _merge_concourse(), _merge_halls(), _merge_house_open_plan(), _paint() (+3 more)

### Community 68 - "Map Origin & Binary Read"
Cohesion: 0.15
Nodes (9): choose_origin(), read_bin(), door_pair(), folder_name(), check_1_3_6(), ways_in(), main(), Report (+1 more)

### Community 69 - "Worldmap Binary IO"
Cohesion: 0.15
Nodes (8): _clean(), _features(), _pieces(), _points(), _polygons(), _ring(), _within_budget(), write_bin()

### Community 71 - "Board Frontend API Client"
Cohesion: 0.16
Nodes (19): bdApiError(), bdFields(), bdLoad(), bdNote(), bdOpenSaved(), bdPresetKind(), bdRefresh(), bdRoomsMarkup() (+11 more)

### Community 72 - "Surroundings Classification"
Cohesion: 0.18
Nodes (5): grid_angle(), _orthogonal_rotation(), place(), _polygon(), rectilinearize_polygon()

### Community 73 - "Roof & Ceiling Tiles"
Cohesion: 0.15
Nodes (10): band_squares(), upper_layers(), level_layers(), north(), preserve_corner(), room(), wall_tiles(), west() (+2 more)

### Community 74 - "Launcher & Port Control"
Cohesion: 0.18
Nodes (9): free_port(), in_a_browser(), main(), report_crash(), serve(), show_in_browser(), wait_for(), check_in_background() (+1 more)

### Community 75 - "Catalog & Window Cutouts"
Cohesion: 0.14
Nodes (8): _all_interior_walls(), _complete_window_cutouts(), escalator_tiles(), floor_entry(), _interior_walls(), _wall_style(), t(), _flat_roofed()

### Community 76 - "Drawing Sheet Design Tests"
Cohesion: 0.18
Nodes (4): cells(), sheet(), SheetSize, WhatIsOnIt

### Community 77 - "Changelog Docs"
Cohesion: 0.18
Nodes (16): KnoxMap changelog, Compile batch retries and failure record (1.3.9, 1.6), Blank Erika tiles dropped from catalog (1.6), Buildings kept off the road (1.6), Guaranteed rifle (1.3.9), Fill gaps from Overture (1.4), Chinese regional architecture (1.6), True map generation (1.3.9) (+8 more)

### Community 78 - "Contributing & Legal Docs"
Cohesion: 0.19
Nodes (15): Contributing guide, Run selftest and layout audit before a PR, Legal notes, GPL-2.0 obligations for compiler, Nominatim one request per second policy, OpenStreetMap ODbL credit requirements, OpenStreetMap tile usage policy, MIT licence for fork additions (+7 more)

### Community 79 - "Rust Main & Cell"
Cohesion: 0.33
Nodes (11): blank(), cell_of(), compare(), compile(), export(), files(), main(), name_of() (+3 more)

### Community 80 - "Path Chain Joins"
Cohesion: 0.17
Nodes (10): _chains(), _extend(), _join(), _key(), level_of(), _line_px(), plan_bridges(), plan_piers() (+2 more)

### Community 81 - "Config & Atomic Write"
Cohesion: 0.13
Nodes (9): elevators_mod_installed(), load_config(), save_config(), save_steam_folders(), spawn_selector_installed(), update_config(), workshop_mod_installed(), _write_config() (+1 more)

### Community 82 - "Rust BMP Encoding"
Cohesion: 0.16
Nodes (8): grey(), le16(), le32(), read_grey(), CHUNK, CHUNKS_PER_SIDE, Grey, PIXEL

### Community 83 - "Rust Pack Encoding"
Cohesion: 0.23
Nodes (12): put_u32(), encode(), expand(), MAGIC, Pack, parse_chunk(), Rec, Skip (+4 more)

### Community 84 - "Workshop Art Generator"
Cohesion: 0.20
Nodes (7): fit(), _font(), letterbox(), main(), render_lots(), thumbnail(), trim()

### Community 85 - "Storey Count Pools"
Cohesion: 0.21
Nodes (3): building_levels(), area_level_pool(), RegionalStoreys

### Community 86 - "NYC Midtown Terrain Docs"
Cohesion: 0.20
Nodes (14): NYC Midtown terrain vs paper map comparison, 7th Avenue, Broadway, Bryant Park, Church of The Holy Innocents, Herald Square, Lyric Theatre, Manhattan street grid (+6 more)

### Community 88 - "Prop Placement"
Cohesion: 0.14
Nodes (4): lattice_on_map(), place_props(), _polygons(), OutdoorProps

### Community 89 - "Rust Cell Type"
Cohesion: 0.22
Nodes (7): at(), Cell, CHUNK, CHUNKS, SIDE, Square, SQUARES_PER_CHUNK_LEVEL

### Community 90 - "Rust ChunkData Parse"
Cohesion: 0.19
Nodes (9): BLOCK, ChunkData, GRID, HEAD, damaged_files_are_errors_not_panics(), header(), header_round_trips(), pack() (+1 more)

### Community 91 - "Preset Frontend Settings"
Cohesion: 0.22
Nodes (14): applyPortablePreset(), changedFrom(), changedSettings(), editReady(), presetNote(), readSettings(), reapply(), rememberMap() (+6 more)

### Community 92 - "Batch Compile Runner"
Cohesion: 0.18
Nodes (7): do_batch(), compile_rust(), phase(), tick(), _end_batch(), _run_batch(), _why()

### Community 93 - "CI Workflow & Release Docs"
Cohesion: 0.19
Nodes (12): knoxlots GitHub workflow, Attach knoxlots binaries to release, Rust knoxlots compiler (1.6), Regression map SHA-256 manifest check, In-game blank chunkdata test procedure, Blank chunkdata accepted by Build 42, Blank chunkdata in-game test, Lot file round-trip verification (+4 more)

### Community 94 - "Language Files & Sketch Docs"
Cohesion: 0.18
Nodes (13): Draw your own map sketch tool (1.6.2), English language template, Spanish translation file, Turkish translation file, Quick start, KnoxMap main window template, Drawing board screen, Numbered build pipeline sidebar (+5 more)

### Community 95 - "Sheet House Floor Plan Images"
Cohesion: 0.22
Nodes (13): Sheet House Floor Plan, Bathroom, Bedroom, Dining Room, Door, Floor 0 (6 rooms, 4 windows), Floor 1 (7 rooms, 4 windows), Hall (+5 more)

### Community 96 - "Picture Pixel IO"
Cohesion: 0.23
Nodes (6): read_rgb(), draw(), _info(), _legend(), render_to(), _step()

### Community 97 - "Row Unit Footprints"
Cohesion: 0.27
Nodes (4): row_units(), Gate, placed(), Split

### Community 98 - "Box Clearing & Cost"
Cohesion: 0.18
Nodes (5): _clear_box(), _clear_of(), _hug(), _largest_component(), _road_share()

### Community 99 - "Cell Source Writer"
Cohesion: 0.24
Nodes (4): cell_source(), _runs_across_levels(), _squares(), CellSourceTests

### Community 100 - "Frontend Map & Preset UI"
Cohesion: 0.21
Nodes (13): apiError(), buildSettingsForm(), importPortablePreset(), loadMaps(), loadSettings(), openMap(), renderResults(), saveFile() (+5 more)

### Community 101 - "Minified JS Helpers"
Cohesion: 0.22
Nodes (13): F(), G(), h(), k(), ke(), me(), ne(), e() (+5 more)

### Community 102 - "Blend Tests"
Cohesion: 0.28
Nodes (3): blend(), BlendTests, run()

### Community 103 - "Sketch Tests"
Cohesion: 0.36
Nodes (3): collection(), Conversion, drawn()

### Community 104 - "Win32 Type Bindings"
Cohesion: 0.24
Nodes (4): run_and_wait(), say(), there(), wWinMain()

### Community 105 - "Apartment Sheet Images"
Cohesion: 0.23
Nodes (12): Apartment building sheet, Bathroom, Bedroom, Dining room, Floor 0 plan (24 rooms, 7 windows, 6 flats), Floor 1 plan (25 rooms, 7 windows, 6 flats), Floor 2 plan (25 rooms, 7 windows, 6 flats), Hall (+4 more)

### Community 107 - "Region Detection"
Cohesion: 0.35
Nodes (3): detect_region(), DetectRegion, geo()

### Community 108 - "Zone Editor Frontend"
Cohesion: 0.26
Nodes (12): addZoneLayer(), drawZoneEditor(), drawZoneList(), loadZoneMeta(), loadZones(), showZoneCount(), zoneDirty(), zoneNote() (+4 more)

### Community 109 - "Leaflet Draw Vendor JS"
Cohesion: 0.17
Nodes (11): o(), Ae(), Ie(), j(), Jt(), Le(), O(), Qt() (+3 more)

### Community 111 - "Pack Reader"
Cohesion: 0.27
Nodes (4): extract_pack(), PackReader, read_png(), split_name()

### Community 112 - "Workshop Check"
Cohesion: 0.23
Nodes (6): check_workshop(), check(), _mod_info(), _png_size(), _read(), summary()

### Community 113 - "Rust Compile & Image"
Cohesion: 0.36
Nodes (6): GreyImage, CellFiles, compile_cell(), Manifest, pack_bytes(), zombie_bytes()

### Community 115 - "Gun Placement"
Cohesion: 0.24
Nodes (5): _biggest(), _centre(), choose(), _survivor(), write()

### Community 116 - "Compile Poll Frontend"
Cohesion: 0.27
Nodes (11): checkLots(), formatLeft(), note(), pollCompile(), refreshLayoutPreview(), renderCensus(), setupPipeline(), showFailedCells() (+3 more)

### Community 119 - "KnoxMap Cover & Wordmark Images"
Cohesion: 0.27
Nodes (9): KnoxMap cover image, Dark background with lime green and off-white palette, KnoxMap cover image, KnoxMap wordmark, Green map pin over diamond platform icon, KnoxMap location pin mark, Project Zomboid, KnoxMap wordmark (+1 more)

### Community 120 - "App Screenshot Images"
Cohesion: 0.22
Nodes (9): KnoxMap app screenshot, Area panel (bounds, area, cells, tiles), Central Park drawn selection, Shape drawing tools (polygon, rectangle, circle), Generate map button, KnoxMap map generator UI, OpenStreetMap basemap (Leaflet), Project Zomboid map target (+1 more)

### Community 121 - "Interior Cutaway Images"
Cohesion: 0.22
Nodes (10): Cutaway bathroom interior with bathtub, Light blue siding house with dark roof, Brown brick house with dark roof, Pink brick ranch house with fenced yard, Sandbox pit in backyard, In-game isometric residential neighborhood, Paved streets with sidewalks and streetlights, White picket fence around yard (+2 more)

### Community 122 - "Building Mask Preview"
Cohesion: 0.22
Nodes (5): _mask(), preview(), _rooms_of(), scale_for(), stack()

### Community 123 - "Room Overlap Tests"
Cohesion: 0.38
Nodes (3): covered(), DrawingOverWhatIsThere, room()

### Community 126 - "Terrain Source Tests"
Cohesion: 0.33
Nodes (3): TerrainSourceTests, main(), make_sources()

### Community 128 - "Lot Render Tool"
Cohesion: 0.27
Nodes (5): main(), read_header(), read_squares(), render(), image()

### Community 129 - "Road Details Painting"
Cohesion: 0.25
Nodes (4): _paint_road_details(), is_colour(), _real_kerbs(), _smooth_road_edges()

### Community 130 - "Minified JS Helpers"
Cohesion: 0.25
Nodes (9): at(), d(), ht(), i(), Li(), Mi(), v(), W() (+1 more)

### Community 131 - "Minified JS Helpers"
Cohesion: 0.31
Nodes (9): be(), De(), m(), p(), pe(), ve(), xe(), ye() (+1 more)

### Community 135 - "Compile Failure Checks"
Cohesion: 0.22
Nodes (5): load(), check_compile_failures(), harness(), fake(), check_compile_records()

### Community 136 - "Floorplan Preview Tool"
Cohesion: 0.39
Nodes (3): floorplan(), main(), overlay()

### Community 137 - "Rooftop & Cutaway Images"
Cohesion: 0.46
Nodes (7): In-game rooftops isometric view, East cutaway building with furnished rooms, North apartment block with stepped rooftop, Tan paved courtyard strip, Grey road network and sidewalks, South foreground cutaway building with furnished rooms, West cutaway building with furnished rooms

### Community 140 - "Dwelling Checks"
Cohesion: 0.25
Nodes (4): looks_like_apartment(), check_dwellings(), share(), check_updater()

### Community 141 - "Room Color Mix"
Cohesion: 0.29
Nodes (5): _mix_for(), room_colour(), room_kinds(), entry(), room_label()

### Community 142 - "Home Door Reachability"
Cohesion: 0.32
Nodes (5): _doors_off_corners(), homes(), joinable(), reaches(), _sides_of()

### Community 143 - "Loot Reset Lua"
Cohesion: 0.50
Nodes (7): confirm(), eachContainer(), KnoxMapResetLoot.around(), KnoxMapResetLoot.inBuilding(), KnoxMapResetLoot.refill(), onFillWorldObjectContextMenu(), refill()

### Community 144 - "Fitting Choice"
Cohesion: 0.25
Nodes (4): choose(), choose_for_kind(), fitting(), for_kind()

### Community 145 - "Editable Tags Frontend"
Cohesion: 0.43
Nodes (8): addEditable(), describeTags(), editCountNow(), loadEditable(), noteEdit(), pickEdit(), showEditCount(), toggleShaping()

### Community 146 - "Minified JS Helpers"
Cohesion: 0.25
Nodes (8): bi(), c(), e(), hi(), Pi(), Qe(), Ti(), u()

### Community 148 - "Render Ground Rules"
Cohesion: 0.32
Nodes (3): _blocks(), load_rules(), main()

### Community 149 - "Wall Corner Checks"
Cohesion: 0.25
Nodes (3): check_wall_corners(), walls_of(), _sides_for()

### Community 150 - "KnoxMap Logo Images"
Cohesion: 0.43
Nodes (7): KnoxMap Logo, Red-Roofed Brick House, Chimney, Isometric floor tile (logo outline), Map pin (logo filled shape), Project Zomboid map, Green Zombie Head

### Community 151 - "Ingame Cutaway Images"
Cohesion: 0.48
Nodes (7): Ingame cutaway isometric map view, Bathroom with bathtub, toilet and sink, Bedroom suite with beds, wardrobes and nightstands, Perimeter wall with windows, Asphalt road network with intersections, Tiled sand-colored ground zones, Left-edge utility room with wall appliance

### Community 153 - "Building Storey & Materials"
Cohesion: 0.29
Nodes (4): style_for(), tally(), _tile_names(), tiles_used()

### Community 156 - "Tower Preview Tool"
Cohesion: 0.38
Nodes (3): main(), panel(), _tiles()

### Community 158 - "Fixture Docs"
Cohesion: 0.47
Nodes (6): Building editor and hand-built presets (1.7), tbx and pzw file format rules, Handmade building fixture cases, WorldEd output as reference fixtures, WorldEd fixtures README, Building editor screen

### Community 161 - "Bitmap Scale Helpers"
Cohesion: 0.40
Nodes (3): bitmap_pixels(), scale_that_fits(), check_worlded_size()

### Community 162 - "Workshop Upload Checks"
Cohesion: 0.33
Nodes (3): check_no_size_wall(), no_download(), check_odd_requests()

### Community 163 - "Tower & Skyscraper Images"
Cohesion: 0.50
Nodes (5): Brick residential towers, Isometric skyscraper city block, Glass curtain-wall towers, Cutaway office floors with furniture, Street and sidewalk ground plane

### Community 164 - "Apartment Layout Images"
Cohesion: 0.60
Nodes (5): Real apartment layout image, Central grey hallway strip with stair/elevator-like icons, Apartment floor 0 plan (17 rooms, 14 windows), Apartment floor 1 plan (18 rooms, 14 windows), Roof plan (41 rectangles)

### Community 165 - "Roads Tiles Images"
Cohesion: 0.50
Nodes (5): Roads in-game tiles comparison, Dashed centre line, Kerb tile, Levittown NY pavements-to-verge layout, Lexington KY grid-to-tiles layout

### Community 166 - "Spawn Comparison Images"
Cohesion: 0.50
Nodes (4): Spawn before/after comparison image, Share of chunks with zombies (13% before, 48% after), Spawn painted from ground colour (BEFORE), Per-chunk zombie cap of 10

### Community 172 - "Street Angle Checks"
Cohesion: 0.60
Nodes (4): check_street_angle(), clip(), grid(), street()

### Community 174 - "Linux Docs"
Cohesion: 0.50
Nodes (4): Linux Qt library load order fix (1.4.2), KnoxMap on Linux and macOS, Qt RUNPATH versus LD_LIBRARY_PATH load order, Wine fallback for map compiler

### Community 175 - "Overpass Docs"
Cohesion: 0.50
Nodes (4): Self-hosted Overpass endpoints (1.6), Self-hosting an Overpass server, overpass_endpoints config setting, Docker Overpass image setup

### Community 176 - "Times Square Render Images"
Cohesion: 0.67
Nodes (3): Circle 250m around Times Square render, Street grid outside the built circle, Times Square

### Community 178 - "Lua Guncache"
Cohesion: 0.83
Nodes (3): boxFor(), onFillContainer(), squareOf()

### Community 180 - "Logo Concept Images"
Cohesion: 0.67
Nodes (4): KnoxMap Logo (Zombie Map Pin), Dark rounded-square background, Isometric floor tile (Project Zomboid map unit), Map pin standing on the floor tile

### Community 181 - "Minified JS Helpers"
Cohesion: 0.67
Nodes (4): Je(), ni(), oi(), si()

## Ambiguous Edges - Review These
- `Bathroom with bathtub, toilet and sink` → `Left-edge utility room with wall appliance`  [AMBIGUOUS]
  docs/images/ingame_cutaway.jpg · relation: conceptually_related_to
- `White siding house with dark roof` → `Cutaway bathroom interior with bathtub`  [AMBIGUOUS]
  docs/images/ingame_houses.jpg · relation: conceptually_related_to
- `Sheet House Floor Plan` → `Wall Between Flats`  [AMBIGUOUS]
  docs/images/sheet_house.png · relation: references

## Knowledge Gaps
- **100 isolated node(s):** `knoxlots`, `SIDE`, `CHUNKS`, `CHUNK`, `SQUARES_PER_CHUNK_LEVEL` (+95 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1364 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **47 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `Bathroom with bathtub, toilet and sink` and `Left-edge utility room with wall appliance`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `Settings` connect `Octilinear Settings Tests` to `Multipolygon Rings & Selftest Geometry`, `Build Pipeline Core`, `Builder API Presets`, `Web App API Endpoints`, `Dwelling Checks`, `Design & Sketch API`, `Layout Kind Assignment`, `Building Style & Materials`, `WorldEd Experiments`, `Wall Corner Checks`, `Building Storey & Materials`, `Notable Buildings & Build Entry`, `Building Plan & Railings`, `Setup Script Utils`, `Kind Assignment & Atriums`, `Builder Autofill API`, `Buildings API & Workers`, `Zones Config`, `Business Layout Tests`, `Designer Autofill`, `Map Report API`, `Map Projector`, `Regression Fixture Checks`, `Map Origin & Binary Read`, `Surroundings Classification`, `Storey Count Pools`, `Render Settings Tests`, `Building Alignment Tests`, `Building Mask Preview`?**
  _High betweenness centrality (0.050) - this node is a cross-community bridge._
- **Are the 2 inferred relationships involving `main()` (e.g. with `Projector` and `_boom()`) actually correct?**
  _`main()` has 2 INFERRED edges - model-reasoned connections that need verification._
- **What connects `knoxlots`, `SIDE`, `CHUNKS` to the rest of the system?**
  _100 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Multipolygon Rings & Selftest Geometry` be split into smaller, more focused modules?**
  _Cohesion score 0.039649122807017545 - nodes in this community are weakly interconnected._
- **What is the exact relationship between `White siding house with dark roof` and `Cutaway bathroom interior with bathtub`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `build()` connect `Build Pipeline Core` to `Multipolygon Rings & Selftest Geometry`, `Interior Room Layout`, `Floorplan Preview Tool`, `Web App API Endpoints`, `PZ Map Colors & Bitmaps`, `Area Spatial Index`, `Dwelling Checks`, `Stop Map Tool`, `Building Style & Materials`, `WorldEd Experiments`, `Octilinear Settings Tests`, `Mod Map Install`, `Notable Buildings & Build Entry`, `Setup Script Utils`, `Headercheck & Room Tables`, `Batch Building Layout Runner`, `OSM Feature Cache & Sea`, `Buildings API & Workers`, `Zones Config`, `Door Fronts & Painting`, `Fence Building`, `Petrol Station Forecourt`, `World File Writer`, `Map Projector`, `Regression Fixture Checks`, `Map Origin & Binary Read`, `Surroundings Classification`, `Catalog & Window Cutouts`, `Storey Count Pools`, `Footprint Geometry`, `Prop Placement`, `Row Unit Footprints`, `Region Detection`, `Gun Placement`?**
  _High betweenness centrality (0.041) - this node is a cross-community bridge._