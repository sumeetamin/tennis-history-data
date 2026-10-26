# Collection and reuse policy

We can collect tennis data ourselves only from sources whose terms permit the intended access and reuse, or after receiving written permission. Personal, non-commercial use does not by itself override a website's terms.

## Current source restrictions

- [ATP Terms of Use](https://www.atptour.com/en/terms-and-conditions) say systematic retrieval of scores, statistics, rankings, or other content to build a database is prohibited without prior express written permission. They also limit use of site content to individual, non-commercial purposes.
- [WTA Terms of Use](https://www.wtatennis.com/terms-and-conditions) prohibit collecting information with automated tools or manually on a mass basis without separate written permission. They also restrict copying and distribution of site material.
- [ITF Terms and Conditions](https://www.itftennis.com/en/about-us/terms-conditions/) restrict copying and redistribution of site content and require prior written consent for distribution to third parties. The ITF content portal separately prohibits automated collection.

These terms mean the project should not run bulk scrapers against ATP, WTA, or ITF sites or publish scraped records from those sites unless permission is obtained. Publicly visible pages are not automatically bulk-download or redistribution licenses.

## Approved collection workflow

Before writing a collector for a source:

1. Record the page or API, its current terms, robots guidance, rate limits, and whether the source grants reuse rights.
2. Obtain written permission when the terms require it. Store the permission scope and any expiry or attribution requirements with the source record.
3. Prefer official downloads or documented APIs. Do not bypass logins, CAPTCHA, access controls, rate limits, or blocks.
4. Use low request rates, cache responses, and respect `Retry-After` and other published limits.
5. Keep the raw source, retrieval date, source URL, checksum, and transformation history where storage is allowed.
6. Publish source data only when the license permits redistribution. Otherwise keep it out of the public repo and publish links, schemas, and independently produced aggregate summaries only when allowed.

## Practical paths

- Start with the Sackmann archive files under their stated CC BY-NC-SA 4.0 terms.
- Ask ATP, WTA, and ITF for permission or a research/data license for gaps, especially comprehensive ITF history.
- Use licensed APIs for private cross-checks only when their terms allow that use; do not republish API data without explicit redistribution permission.
- Invite contributors to add records from materials they have rights to share, with source citations and provenance for every contribution.
