---
type: reference
status: current
created: 2026-10-01
updated: 2026-10-04
tags: [get-brolls, catalogs, providers, search, access]
---

# Source catalogs: search, access, and acquisition

Use this reference when choosing a catalog or implementing a provider. It consolidates the supplied 18-source inventory, the researched EC/UN/Destockd routes, and Instagram/TikTok. Catalog descriptions guide the agent's selection; they are not fixed topic-to-provider rules.

**Status scope:** `Search` and `URL/browser` below describe code present in this get-brolls checkout on 2026-10-04, not a live availability guarantee. `Planned` means the route is retained from prior research but has no adapter here. Statements that an integration was implemented in the supplied notes refer to the previous project. Credentials and sessions from that project are not assumed to be available here. Dated Archive.org observations are recorded separately in [QUALITY.md](QUALITY.md); other retained endpoints were not re-probed for this update.

Operational CLI instructions remain in [GUIDE.md](GUIDE.md); provider selection and the personal library are covered in [providers.md](../references/providers.md).

## Catalog overview

| Catalog | Best material to look for | Search/access route | Current get-brolls support |
|---|---|---|---|
| YouTube | Named people, speeches, official channels, news, events | yt-dlp search; no YouTube API key | Search |
| Wikimedia Commons | Historical photos, documents, video | Public MediaWiki Action API | Search |
| Internet Archive | Archival films, newsreels, FedFlix, images | Public search and item Metadata API | Search + explicit item/file URL; inspect/preview/common delivery |
| NASA Image and Video Library | Space, science, NASA media | Public Images API; no general NASA API key | Search |
| Library of Congress | Historical films, photos, maps, documents | Public JSON API and item resources | Planned |
| DVIDS | Official military footage, exercises, briefings | Application API key | Planned |
| Europeana | European cultural and historical collections | Personal/project API key according to use | Planned |
| NARA | US national archival records and media | Catalog API key; separate API/storage conditions | Planned |
| Pexels | Illustrative atmosphere and context | Pexels API key; current adapter searches video | Search |
| Pixabay | Illustrative atmosphere and context | Pixabay API key; current adapter searches video | Search |
| Mapillary | Images of a particular street or place | Client token and geographic search | Planned |
| Telegram | Posts and attachments in selected public channels | Telethon, application credentials, user session | Planned |
| GDELT TV | Locating a television segment and time reference | Public TV search API; locator role | Planned |
| X | Public posts, exact quotations, attached media | Prior route: xAI X Search through agreed Grok OAuth | Planned |
| EC Audiovisual Service | EU events, speeches, stockshots, institutional photos | AV Portal client endpoint, then portal backend | Planned |
| UN Web TV | UN meetings, briefings, speeches | UN Transcripts API; catalog/direct links for older video | Planned |
| UN Audiovisual Library | UN historical footage and high-quality originals | Archive cards and footage request/licensing | Planned |
| Destockd | Individual shots from FedFlix films | Website discovery and direct shot links | Planned |
| Instagram | Reels, participant posts, contemporary event footage | Authorized browser; video/audio acquisition route | URL/browser; no CLI keyword search |
| TikTok | Short event footage and participant posts | Browser discovery, canonical post URL, yt-dlp | URL/browser; no CLI keyword search |

## YouTube

- **Search:** yt-dlp `ytsearch` with a query selected by the agent. The current adapter retrieves titles, creators, duration, thumbnails, and canonical video URLs. YouTube Data API is optional in the old design, not a requirement of this checkout.
- **Inside a video:** current `inspect` uses subtitles, chapters, and description timestamps; previews confirm what is visible. The prior design's Gemini timestamp finder is an extension, not implemented automatic visual search here.
- **Access/acquisition:** yt-dlp and FFmpeg; a specific video may require a session or have regional restrictions. Register the canonical video ID and actual source interval.
- **Keep:** channel, event/date context, source URL, interval, real dimensions, and item-specific conditions. A news upload can contain archive footage or third-party inserts.
- **Reference:** [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Wikimedia Commons

- **Search:** public Action API, file namespace, media-type filtering, then file metadata. Current code uses `imageinfo` with URL, dimensions, MIME type, and `extmetadata`; images and videos are supported.
- **Video detail:** the prior research also calls for derivatives, `videoinfo`, and timed text when available. These are capabilities to inspect per file, not a claim that the current search adapter collects all of them.
- **Acquisition:** choose a real downloadable representation; the original may be WebM or another format rather than MP4. A timestamped thumbnail/preview does not prove server-side video cutting.
- **Keep:** the file page, creator, exact license, attribution, and chosen representation. Unknown license stays unknown.
- **Reference:** [Commons API](https://commons.wikimedia.org/wiki/Commons:API/MediaWiki).

## Internet Archive / Archive.org

- **Search:** public catalog search, then `/metadata/{identifier}`. Restrict by media type, collection, subject, date, or creator when useful.
- **Critical distinction:** one item can contain several independent videos. Enumerate its files and identify the actual media asset; the item is not necessarily one film or one downloadable file.
- **Inside a video:** collect captions when present. Use a smaller proxy for exploration and a suitable high-quality representation for the selected interval. A catalog match does not supply shot boundaries automatically.
- **Access/acquisition:** public metadata is generally readable without login; restricted files require their own access check. Preserve item ID, file identity, and the canonical item page.
- **Keep:** item/asset provenance and rights. FedFlix or a collection name alone does not establish the rights of every included fragment.
- **Implemented slice:** `archive` search, actual file/representation selection, associated captions, restrictions, and resumable fragment chains use the common ledger and review route. A chain is one to five allowed catalogs. Each catalog has three meaningful queries. Confirmed suitable options carry across catalogs. One additional disjoint pass is allowed and a third pass is not. Suitable-option confirmation names the viewed preview or acquired file, groups identical stills and near-duplicate trims, and can keep several scenes of one source with `preview --option`. Three current distinct options stop later dispatches. An unassessed result or interrupted query on the current catalog blocks the additional pass and a shortfall until `search-assess`. Rejection leaves the count until a new visual confirmation; approval alone does not restore it. Catalogs without an implemented keyword-search route can be planned, and a query there is refused instead of invented. Other planned adapters, browser import, and whether a preview-confirmed requested original counts remain separate. [Operational commands](GUIDE.md#provider--archiveorg-and-fragment-search).
- **References:** [search guide](https://archivesupport.zendesk.com/hc/en-us/articles/360018359991-Search-A-Basic-Guide), [Metadata API](https://archive.org/developers/metadata.html).

## NASA Image and Video Library

- **Search:** `https://images-api.nasa.gov/search`, using text and media type; resolve the selected `nasa_id` through `/asset/{nasa_id}`.
- **Access:** this media catalog does not require the general NASA developer API key. Current code supports images and video.
- **Acquisition:** inspect the asset list for an appropriate original/representation rather than using the search thumbnail as the final media.
- **Keep:** creator/center, date, NASA ID, source page, and item conditions, including third-party authorship.
- **References:** [API documentation](https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf), [media conditions](https://www.nasa.gov/nasa-brand-center/images-and-media/).

## Library of Congress

- **Search:** public JSON responses (`fo=json`), keyword query, and facets for format, collection, date, place, language, or contributor. Available full text can include video transcripts.
- **Acquisition:** inspect item resources and their actual file variants. Prefer the master/highest available quality, especially for maps and scans, rather than a small web derivative.
- **Inside a video:** use transcripts when supplied. Streaming Services operations are usable only when confirmed for the particular file; otherwise use available MP4/HLS or report the operation as unsupported.
- **Keep:** item/resource identifiers, actual file, source page, date, and item-level rights/access statements.
- **References:** [APIs](https://www.loc.gov/apis/), [query parameters](https://www.loc.gov/apis/json-and-yaml/requests/parameters/).

## DVIDS

- **Search:** official Search API with an application key. Useful filters include video type, `B-Roll` category, branch, country, city, date, duration, and HD status.
- **Access:** search/read integration needs the issued API key; upload permissions are unnecessary. Configure this project independently of any earlier installation.
- **Acquisition:** resolve the selected asset and available files; a search thumbnail is not the editing original.
- **Keep:** asset ID, unit/creator credit, capture date versus publication date, location, and usage conditions. Official footage may still be archival relative to the narrated event.
- **References:** [API access](https://api.dvidshub.net/docs), [Search API](https://api.dvidshub.net/docs/search_api).

## Europeana

- **Search:** Search API, then the selected record. Use the relevant collection, media type, date, place, and language metadata.
- **Access:** the retained design distinguishes a personal key for trials and a project key under the conditions for the intended application. Check the current key terms before enabling the adapter.
- **Acquisition:** inspect links to the holding institution and its media; a Europeana record does not guarantee a direct downloadable original.
- **Keep:** Europeana ID, holding institution, original record/media link, creator/date, and the record's rights statement.
- **References:** [APIs](https://api.europeana.eu/en), [API keys](https://www.europeana.eu/en/how-to-register-for-and-manage-an-api-key).

## NARA

- **Search:** National Archives Catalog API using its required key, then record details and digital objects.
- **Access:** the supplied research records that a key and a read-only probe existed in the old project. This does not configure the new project, and an older note about a missing key is not evidence of a permanent access barrier.
- **Acquisition:** inspect the actual digital files. Catalog API access/storage conditions and rights in a photograph or film are separate checks.
- **Keep:** catalog identifier, record/collection context, date, digital object, source page, and rights restrictions.
- **Reference:** [Catalog API](https://www.archives.gov/research/catalog/help/api).

## Pexels

- **Search:** Pexels video API with `PEXELS_API_KEY`. The current adapter searches video; the wider catalog's photos are not an implemented photo-search route here.
- **Acquisition:** select a suitable MP4 variant and refresh the asset by ID before final acquisition.
- **Use:** illustrative atmosphere/context when stock has been explicitly requested; preserve that distinction from footage of a named event.
- **Keep:** creator, asset ID/page, real dimensions, and Pexels license/API conditions.
- **Reference:** [API documentation](https://www.pexels.com/api/documentation/).

## Pixabay

- **Search:** video API with `PIXABAY_API_KEY`; current search responses are cached for 24 hours. Photo search is not implemented by this adapter.
- **Acquisition:** resolve by ID and choose the actual video variant. Respect request limits and restrictions on mass downloading.
- **Use/keep:** illustrative stock only under the project's stock policy; record creator, source page, dimensions, and usage conditions. A preview-image sequence number is not a known video second without an explicit mapping.
- **Reference:** [API documentation](https://pixabay.com/api/docs/).

## Mapillary

- **Search:** geographic/bounding-box search using a client token. Supply a real location or coordinates; generic topic keywords alone are insufficient for the retained route.
- **Result:** street-level images of a place, not a general source of moving footage.
- **Keep:** image/sequence ID, coordinates, capture date, creator, source link, and applicable conditions. Confirm the image actually shows the requested place.
- **Reference:** [API examples](https://github.com/mapillary/api-demo/blob/main/README.md).

## Telegram via Telethon

- **Search:** bounded history/text search within an explicit whitelist of public channels, using `api_id`, `api_hash`, and an authorized user session.
- **Scope from prior research:** a whitelist was derived from a selected channel folder. Preserve an explicit channel list for this project; authorization does not mean access to all subscriptions or private conversations is in scope.
- **Acquisition:** inspect the selected message and its attachments. Preserve channel, message ID/permalink, timestamp, caption, and attachment identity; reposts need original-source verification.
- **Limits:** store a cursor and avoid repeatedly reading unchanged messages. Handle short FloodWaits within the run; record longer waits as the next eligible access time and continue with other sources.
- **Privacy:** keep credentials and session files private; reports contain public provenance, not session material.
- **References:** [application credentials](https://core.telegram.org/api/obtaining_api_id), [Telethon errors and limits](https://docs.telethon.dev/en/stable/concepts/errors.html).

## GDELT TV

- **Search:** public TV API for finding a broadcast segment and temporal reference.
- **Result:** a locator. Treat caption-based matches and any visual/AI search route as separate capabilities with their own actual channel/date coverage.
- **Acquisition:** establish where the underlying broadcast can be viewed and obtained. A search hit is not a promise of a downloadable or cleared editing file.
- **Keep:** broadcaster/program, broadcast time, matching text or evidence, locator URL, and the eventual media source.
- **Reference:** [TV API](https://blog.gdeltproject.org/gdelt-2-0-television-api-debuts/).

## X

- **Retained route:** discovery through xAI `x_search` using the previously agreed Grok OAuth mode. The old research records a successful search, not complete proof of media download or token refresh. This route is not integrated or live-verified here.
- **Search:** use supported account/date filters and preserve the post URLs returned. Confirm exact quotations against the original post.
- **Acquisition:** original-post retrieval, screenshot capture, and media download are separate operations. X Search is not a downloader; Grok OAuth does not substitute for credentials of a separate X API integration.
- **Access:** verify supported model/tool, login, expiry, and refresh/re-login independently. Preserve the chosen OAuth mode rather than silently switching to API billing or a different model. Provider subscription limits still apply.
- **Keep:** original post, author, date, original language, attached media, and source provenance. Keep translations and styled quotation cards separate from the original.
- **Reference:** [xAI X Search](https://docs.x.ai/developers/tools/x-search). The subscription/OAuth route above is retained from project-specific research, not established solely by the public API guide.

## EC Audiovisual Service

**Retained provider ID:** `ec_audiovisual`. The supplied integration note describes an implementation in the old project; the route still needs an adapter and validation in this checkout.

### Researched access route

Primary: the AV Portal client endpoint used by the Drupal/OpenEuropa integration:

```text
https://gfdwwnbuul.execute-api.eu-west-1.amazonaws.com/avsportal/avsportal
```

Fallback when the primary fails: the current-portal backend recorded in the research:

```text
https://8hwk2cyeyb.execute-api.eu-west-1.amazonaws.com/parrotfish-prod/
```

The supplied note reports credential-free read-only calls: no API key, OAuth, or account. These endpoints have no public versioned API contract or SLA. Revalidate the client/schema with a bounded probe before enabling the integration. Browser-embedded bearer values are not part of this route and must not become credentials or dependencies.

### Search and shot metadata

- Video-first search: **`VIDEOSHOT` → `VIDEO`**. Search exact catalog segments before whole videos.
- Retained adapter options: `kind=video` searches both; `segments=false` searches whole videos only; `kind=image` searches `PHOTO`/`REPORTAGE`; `kind=all` searches all four record types. These are proposed adapter options, not get-brolls CLI flags.
- Preferred metadata/media language: `EN`; retained fallback order: `INT`, English, French, then the first available language.
- Preserve shot reference as the candidate identity, parent/document reference as the public page, `timecodeIn` as `provider_source_start`, and `shotduration` as `provider_shot_duration`/candidate duration.
- A shot's media representation may be the parent video. Apply its source start exactly once; an explicitly chosen `source_start` overrides the provider start.
- Video preference: direct H.264 1080p → 720p → 480p → legacy high/low → HLS. Photos: `ORIGINAL`, then the best available variant; normalize protocol-relative/relative media URLs.

### Conditions and recovery

- Preserve copyright holder/year/scope, detailed third-party exceptions, and the EC conditions link. Empty or numeric `cc_by` is not evidence of a Creative Commons license.
- `download_enabled=N` / `isDownloadable=false`: retain the candidate, shot timecode, and warning for human review. The retained design requires an explicit access decision before acquisition; that decision does not itself prove reuse rights. Playback availability does not remove the restriction. A changed brief requires a new decision.
- The old adapter used a one-hour read-only JSON cache and at most five returned candidates. Keep searches bounded; these are retained integration settings, not universal portal limits.
- Recovery: bounded health probe → Drupal client configuration/parser schema → fallback backend → inspect current portal network calls if both fail. Browser scraping is a last diagnostic route. EC technical contacts can clarify support/rate limits; waiting for an undocumented developer key is not a prerequisite of this route.
- **References:** [client module](https://www.drupal.org/project/media_avportal), [client code](https://git.drupalcode.org/project/media_avportal), [endpoint/DNS discussion](https://github.com/openeuropa/media_avportal/issues/95), [conditions](https://audiovisual.ec.europa.eu/en/conditions-of-use), [contacts](https://audiovisual.ec.europa.eu/en/contact).

## UN Web TV

**Retained provider ID:** `un_webtv`. Keep this separate from the Audiovisual Library.

- **Full-text route:** public UN Transcripts search; use `ft=1` to search transcript content rather than only meeting titles:

  ```text
  https://transcripts.un.org/en/meetings.json?q=QUERY&ft=1
  ```

- API read endpoints require no authentication. Select the supported locale/language for the requested transcript; the documented locales include `en`, `fr`, `es`, `ar`, `zh`, and `ru`.
- **Coverage:** meeting search covers the last 365 days. For older events, use the Web TV catalog or a direct `webtv.un.org/en/asset/...` URL/asset ID. Empty transcript search is incomplete coverage, not proof that no recording exists. A sitemap can discover URLs but is not full-text speech search.
- **Inside a meeting:** retain matching text, speaker, date, language, and source timing; canonical/deep links with `?t=` point to the spoken moment. The transcripts are generated automatically and are not official UN records.
- **Acquisition:** after selection, check actual representations through yt-dlp on the public Web TV page; the retained route uses its Kaltura player. Preserve the canonical page, not an expiring signed stream URL. Keep the candidate visible for an explicit access/rights decision before acquisition.
- **High-quality original:** refer to UN Audiovisual Library when the available Web TV representation is insufficient.
- **References:** [Transcripts API](https://github.com/united-nations/transcripts/blob/main/docs/api.md), [Web TV](https://webtv.un.org/), [UN media services](https://media.un.org/en/about-us).

## UN Audiovisual Library

**Retained provider ID:** `un_avlibrary`. This is an archive locator and footage-request route.

- **Search/access:** website discovery, public cards, and direct URL/Asset ID. The supplied research found no universal public search API; do not invent one.
- **Keep:** title, date, description, preview reference, shotlist/time markers when available, asset ID, and the footage-request link.
- **Acquisition:** a candidate marked `license_required` remains useful and visible. Public preview is a viewing reference, not a cleared editing original. The user requests the selected asset/interval; import the officially supplied file together with its conditions.
- **Rights:** UN archive footage is not public domain. Authorization/license agreement and possible fees apply under the library's published guidelines.
- **UNifeed:** retained as a UN news-service variant, not an independently confirmed provider ID in the supplied inventory.
- **References:** [guidelines](https://media.un.org/avlibrary/en/guidelines), [request footage](https://media.un.org/avlibrary/en/contact/request_footage).

## Destockd

**Retained provider ID:** `destockd`. Its value is the division of FedFlix films into individual shots.

- **Initial route:** search the website and import the direct shot link; retain film title and shot ID.
- **Special access finding:** the supplied research records `Disallow: /api/` in `robots.txt`. The discovered JSON API is undocumented. Preserve website/link import until the operator agrees to a programmatic access method and request rate; the robots finding was not re-probed for this document.
- **Shot detail:** preview, exact boundaries, and the source-film link can be visible in the UI, but cannot be inferred from the hash-route URL. Missing values remain unknown.
- **After agreed API access:** bounded read-only requests, cache, and schema checks; keep manual import as fallback. Whole-catalog crawling and protection bypass are outside the retained route.
- **Acquisition:** connect the shot to its original film through Archive.org when the metadata/link is available. Preserve Destockd shot ID and Archive.org item/file identity separately. Automatic preview/original import is not established by the supplied locator implementation.
- **Rights:** verify the actual original and third-party inserts; a general “public domain or unrestricted” label is not sufficient item evidence.
- **References:** [website](https://destockd.com/), [robots.txt](https://destockd.com/robots.txt).

## Instagram

- **Discovery:** agent-operated browser search/profile browsing in an authorized session. There is no global Instagram keyword search in the current CLI.
- **Optional external search route:** Agent Reach documents OpenCLI user search, profiles, recent posts, and Explore through an existing logged-in Chrome session. This is an integration option, not installed get-brolls functionality or proof of full-content keyword search.
- **Current acquisition route:** browser/Playwright → capture video and audio representations of the same Reel → private temporary configs → pair collector/curl → FFmpeg merge → ffprobe/full decoding. yt-dlp by full post URL is another route when it works for the item.
- **Critical pairing:** match Reel ID/manifest/asset identity and duration. Preloaded recommendations may supply unrelated streams; the first two MP4 requests are not sufficient evidence. `blob:` is not a downloadable source URL.
- **Keep:** canonical Reel URL, account, caption/context/date, and selected representation. Signed CDN URLs/configs remain private and may need recapture after expiry. The capture tool must actually expose the required responses; the pair collector does not discover them itself.
- **References:** [current browser/acquisition procedure](GUIDE.md#instagram--navegadorplaywright-dois-streams-e-mp4), [Agent Reach access option](https://github.com/Panniantong/Agent-Reach/blob/main/docs/README_en.md#supported-platforms).

## TikTok

- **Discovery:** browser → complete canonical `https://www.tiktok.com/@USER/video/ID` URL. Resolve shortened links first. The current CLI has no global TikTok keyword search.
- **Profile discovery detail:** the current guide records `https://www.tiktok.com/embed/@USER` as a way to discover recent post IDs when the ordinary logged-out profile grid is empty or challenged. Check this route for the actual profile; it is not a guaranteed universal bypass or a global search API.
- **Acquisition:** yt-dlp on the full post URL; resolve gathers title, handle, creator, and duration when the metadata request succeeds. Individual posts may require a session or be inaccessible.
- **Keep:** post ID, canonical page, account, date/context, source language, and conditions. A discovered embed/post address is not reuse authorization.
- **Reference:** [current TikTok procedure](GUIDE.md#provedor--tiktok).

## Shared catalog result information

Keep the canonical page and original item/asset ID, source date/location/creator, actual media representation, and any known interval or provider timing. Separate discovery, preview, technical acquisition, reuse conditions, and human acceptance. A manual/license-required candidate remains visible with its acquisition method. Record actual search coverage and access errors so a limited or failed search is not reported as absence of footage.

Local files are an import route rather than another catalog. Import them with their source provenance under the existing guide. Coverr and Unsplash were explicitly excluded in the supplied final source inventory and are not added to this reference's target catalog list.

## Integration design

The accepted [fragment-specific search chain planning decision](adr/0001-fragment-catalog-search-chain.md) records the search behavior and an integrated rollout covering the complete target inventory. [CONTEXT.md](../CONTEXT.md) defines its domain terms; neither document establishes additional implemented provider capabilities.

The accepted [catalog integration specification](SPEC-CATALOG-INTEGRATION.md) defines implementation contracts and offline/live acceptance checks for this scope.
