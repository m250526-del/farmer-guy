# Crop Knowledge Documents

This folder contains markdown documentation for crops supported by KisaanDost (FarmAI).

## Naming Convention
- One markdown file per crop.
- Name each file with the lowercased English crop name and a `.md` extension.
  - Examples: `cotton.md`, `wheat.md`, `rice.md`, `mango.md`, `sugarcane.md`.
- The crop name used in vector metadata is automatically derived from the filename stem (e.g. `cotton.md` -> `crop="cotton"`).

## Document Structure Guidelines
Organize sections using standard Markdown headings (`#`, `##`, `###`).
The heading hierarchy forms the `heading_path` stored with each chunk (e.g., `Cotton > Pests > Whitefly`).

Example structure:
```markdown
# Cotton

## Overview
Key agronomic facts, climate, soil requirements, and sowing seasons in Punjab and Sindh.

## Irrigation Schedule
Watering critical stages (flowering, boll formation) and delta of water.

## Pests & Diseases
### Whitefly
Identification, nymph stages, damage symptoms, ETL (Economic Threshold Level), and chemical/biological control.

### Pink Bollworm
Scouting, trapping, and management recommendations.

## Fertilizer Management
Basal and top-dressing requirements (NPK, Zinc, Boron).
```

## Supported Languages
Markdown files can be written in English, Urdu (اردو), or Roman Urdu. The chunker is fully Unicode and Urdu-aware.

