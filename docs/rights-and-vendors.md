# Rights and vendor boundaries

## Project rights

Copyright © 2026 David Villero, to the extent of copyrightable contributions owned by the author. All rights reserved. This project includes AI-assisted implementation; no claim is made to copyright in material that is not legally protectable or not owned by the author.

No open-source or other project-code license is granted by this publication. Rights arising under GitHub's terms, applicable law, and third-party licenses are unaffected. Public visibility is not a general permission to reuse, distribute, sublicense or commercialize the author's protected code or documentation. Request permission through [David Villero's public profile](https://github.com/DavidVillero). This notice does not grant rights to vendor technology or prevent independent development of similar ideas.

GitHub permits users to view and fork public repositories under its terms. Making this repository private later cannot recall existing copies. See [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).

## Independent implementation

This project is not affiliated with, endorsed by or approved by Garmin, Google, Zepp or OpenAI. Product names and trademarks identify external services and remain the property of their respective owners. No vendor apps, SDK archives, proprietary executables or installed dependencies are bundled. Refer to [dependency boundaries](dependencies.md); no complete transitive license or ownership certification is claimed.

## Vendor access is a separate question

This release does not include a direct Garmin sync adapter. Any future adapter should use Garmin's official [Personal API](https://developer.garmin.com/gc-developer-program/overview) under its terms. Health Connect ingestion is a separate route and does not contact Garmin.

Garmin publishes service terms and official integration guidance. The account's applicable jurisdiction and supplemental terms must be checked; do not assume one regional terms page governs every account. Sources: [Garmin terms](https://www.garmin.com/en-US/legal/terms-of-use/) and [official Personal API guidance](https://support.garmin.com/en-US/?faq=HfTwLfw1Gn2A7WS1GdAMH8).

The Android bridge reads records through user-granted Health Connect permissions. This is not certification under Google Play or vendor-app policies. Anyone distributing an app must satisfy applicable permission, disclosure and privacy requirements: [Health Connect publishing](https://developer.android.com/health-and-fitness/health-connect/publish). Zepp and Garmin account/app-specific terms remain separate obligations.

## Source candidate, not production approval

No real health data, credentials, databases, signing keys or production configuration are included. Tests use synthetic inputs. Device and live-client acceptance remain pending; known security limitations are recorded in [security status](security-status.md) and [deployment acceptance](deployment-acceptance.md). Publication does not imply clinical validation, vendor permission or a legal-compliance certification.
