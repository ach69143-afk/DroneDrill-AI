# DroneDrill AI — Background Assets Credits

All 8 background terrain and sky environment backdrops located in this directory are abstract, synthetic training visuals that are AI-generated (Flow) specifically for the DroneDrill AI simulation environment.

## Image Manifest (1920x1080 JPEG, Optimized < 400 KB)

| File Name | Description | Source | Status |
| :--- | :--- | :--- | :--- |
| `open_day.jpg` | Flat open terrain horizon under daytime conditions | AI-generated (Flow) | Tracked (< 400 KB) |
| `open_night.jpg` | Flat open terrain horizon under night sky conditions | AI-generated (Flow) | Tracked (< 400 KB) |
| `urban_day.jpg` | Urban city skyline backdrop under daytime conditions | AI-generated (Flow) | Tracked (< 400 KB) |
| `urban_night.jpg` | Urban city skyline backdrop under night sky conditions | AI-generated (Flow) | Tracked (< 400 KB) |
| `forest_day.jpg` | Dense forest tree canopy horizon under daytime conditions | AI-generated (Flow) | Tracked (< 400 KB) |
| `forest_night.jpg` | Dense forest tree canopy horizon under night sky conditions | AI-generated (Flow) | Tracked (< 400 KB) |
| `hills_day.jpg` | Rolling hills terrain ridge under daytime conditions | AI-generated (Flow) | Tracked (< 400 KB) |
| `hills_night.jpg` | Rolling hills terrain ridge under night sky conditions | AI-generated (Flow) | Tracked (< 400 KB) |

## Dynamic Atmospheric Synthesis

- **Dusk (`<terrain>_dusk`)**: Synthesized dynamically at runtime using the corresponding daytime terrain asset (`<terrain>_day.jpg`). The simulator engine darkens the base layer (~60%), applies an atmospheric purple-to-orange gradient band at the horizon, and overlays an atmospheric blue cooling tint.
- **Offline Self-Containment**: If any image asset is missing from this directory, the simulator engine seamlessly falls back to procedural vector sky/terrain canvas rendering with zero runtime errors.
- **Notice**: These assets contain abstract synthetic training scenery only. No real military locations, installations, or copyrighted real-world imagery are depicted.
