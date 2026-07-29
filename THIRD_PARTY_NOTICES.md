# Third-Party Notices

Caption Studio is distributed under Apache License 2.0. The following direct components and redistributed runtime assets retain their own licenses.

| Component or asset | Purpose | License | Source |
|---|---|---|---|
| React and React DOM | Browser interface | MIT | https://github.com/facebook/react |
| Lucide React | Interface icons | ISC | https://github.com/lucide-icons/lucide |
| Vite and `@vitejs/plugin-react` | Web build tooling | MIT | https://github.com/vitejs/vite |
| TypeScript | Type checking | Apache-2.0 | https://github.com/microsoft/TypeScript |
| Vitest | Web tests | MIT | https://github.com/vitest-dev/vitest |
| mlx-whisper | Apple Silicon speech recognition | MIT | https://github.com/ml-explore/mlx-examples |
| faster-whisper | Docker/Linux speech recognition | MIT | https://github.com/SYSTRAN/faster-whisper |
| CTranslate2 and PyAV | faster-whisper runtime | MIT and BSD-3-Clause | Their respective distributions |
| FFmpeg | Media probing, extraction and rendering | LGPL-2.1-or-later / GPL-2.0-or-later depending on build configuration | https://ffmpeg.org |
| Noto CJK fonts | Docker subtitle font fallback | SIL Open Font License 1.1 | https://github.com/notofonts/noto-cjk |

The repository lock file and a release SBOM are the authoritative dependency inventory for a specific build. Model weights are downloaded at runtime and are not redistributed by this repository; users must review each model's license before use.
