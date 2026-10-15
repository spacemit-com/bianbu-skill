---
schema_version: 2
---
# Skill Card: vibe-coder

## Capability

Generate, edit and validate offline native HTML/CSS/JavaScript applications for SpacemiT K3 riscv64/Bianbu from natural language requests. The bundled validation/preview scripts depend only on the Python 3 standard library; no CDN, remote fonts, npm build chain or runtime download is used.

## Use Cases

User asks for a new offline, browser-playable HTML application (e.g. calculator, chess) on Bianbu, or asks to modify an existing offline HTML app and re-run full validation.

## Inputs and Outputs

Input: Natural-language app requirements and an optional target directory.
Output: Runnable index.html, styles.css, app.js and README.md in the target directory, plus structured validation output (validation.json) containing an ok flag and an error list.

## Dependencies

Python 3 with the standard library only, for the validation and preview scripts. The target device is SpacemiT K3 / Bianbu riscv64.

## Limitations

Applies to offline native HTML/CSS/JavaScript apps for K3/Bianbu only; not for cloud frameworks, external CDNs or native mobile applications. Validation checks static rules; browser-level interaction testing depends on locally available components. The skill must not claim an app works without verification evidence.

## Maintainer

Owner: dec
Contact: decheng.liu@spacemit.com
