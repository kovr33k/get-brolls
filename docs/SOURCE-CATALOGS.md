---
type: reference
status: current
created: 2026-10-01
updated: 2026-10-07
tags: [get-brolls, catalogs, providers, search, access]
---

# Source catalogs: search, access, and acquisition

Use this reference when choosing a catalog or implementing a provider. It consolidates the supplied 18-source inventory, the researched EC/UN/Destockd routes, and Instagram/TikTok. Catalog descriptions guide the agent's selection; they are not fixed topic-to-provider rules.

**Status scope:** `Search` and `URL/browser` below describe capabilities in version 2.13.8, reconciled on 2026-10-07, not a live availability guarantee. The [engineering acceptance](CATALOG-ACCEPTANCE.md) is complete for all twenty retained catalogs. Credentials and sessions from the previous project are not assumed to be available here. [QUALITY.md](QUALITY.md) summarizes current evidence and links to dated source reports. Configured access, acquired media, visual suitability and human acceptance remain separate facts.

Operational CLI instructions remain in [GUIDE.md](GUIDE.md); provider selection and the personal library are covered in [providers.md](../references/providers.md).

## Catalog overview

| Catalog | Best material to look for | Search/access route | Current get-brolls support |
|---|---|---|---|
| YouTube | Named people, speeches, official channels, news, events | yt-dlp search; no YouTube API key | Search |
| Wikimedia Commons | Historical photos, documents, video | Public MediaWiki Action API | Search |
| Internet Archive | Archival films, newsreels, FedFlix, images | Public search and item Metadata API | Search + explicit item/file URL; inspect/preview/common delivery |
| NASA Image and Video Library | Space, science, NASA media | Public Images API; no general NASA API key | Search |
| Library of Congress | Historical films, photos, maps, documents | Public JSON API and item resources; authorized browser for verification challenges | Search + item/resource originals; bounded browser fallback + supplied-original import; API live access unverified |
| DVIDS | Official military footage, exercises, briefings | Application API key; optional server secret | Search + selected asset/files; common inspect/preview/review gates |
| Europeana | European cultural and historical collections | Confirmed personal/project key type according to use | Search + Record API and institution media; absent originals stay manual locators |
| NARA | US national archival records and media | Catalog API key; separate API/storage conditions | Search + explicit NAID/digital-object selection; common preview/review gates |
| Pexels | Illustrative atmosphere and context | Pexels API key; current adapter searches video | Search |
| Pixabay | Illustrative atmosphere and context | Pixabay API key; current adapter searches video | Search |
| Mapillary | Images of a particular street or place | Client token and geographic search | Geographic image search, URL/preview |
| Telegram | Posts and attachments in selected public channels | Telethon, application credentials, user session | Bounded public whitelist route; one dated video acquisition/preview sample in QUALITY |
| GDELT TV | Locating a television segment and time reference | Public TV search API; separate linked original | Implemented; dated caption/locator sample, restricted original |
| X | Public posts, exact quotations, attached media | Retained xAI X Search through agreed Grok OAuth | Bounded OAuth discovery; separate original viewing and manual media/capture import |
| EC Audiovisual Service | EU events, speeches, stockshots, institutional photos | AV Portal client endpoint, then portal backend | Implemented; one decoded shot sample |
| UN Web TV | UN meetings, briefings, speeches | UN Transcripts API; catalog/direct links for older video | Implemented; transcript/player metadata and a decoded 1280×720 working window; editing original not cleared |
| UN Audiovisual Library | UN historical footage and high-quality originals | Browser attempt/import, asset URL/ID and supplied original | URL/browser; original request remains manual |
| Destockd | Individual shots from FedFlix films | Browser attempt/import, shot preview and Archive original link | URL/browser; no undocumented API calls |
| Instagram | Reels, participant posts, contemporary event footage | Authorized browser; video/audio acquisition route | URL/browser; no CLI keyword search |
| TikTok | Short event footage and participant posts | Browser discovery, canonical post URL, yt-dlp | URL/browser; no CLI keyword search |

## YouTube

- **Search:** yt-dlp `ytsearch` with a query selected by the agent. The current adapter retrieves titles, creators, duration, thumbnails, and canonical video URLs. YouTube Data API is optional in the old design, not a requirement of this checkout. `--media image` is refused by the shared search command; the provider function itself still ignores that flag rather than failing.
- **Inside a video:** current `inspect` uses subtitles, chapters, and description timestamps; previews confirm what is visible. The prior design's Gemini timestamp finder is an extension, not implemented automatic visual search here.
- **Access/acquisition:** yt-dlp and FFmpeg; a specific video may require a session or have regional restrictions. Register the canonical video ID and actual source interval.
- **Keep:** channel, event/date context, source URL, interval, real dimensions, and item-specific conditions. When yt-dlp reports non-public availability, an integer age limit, or a live/upcoming/post-live status, that list is stored on `limitations`. A missing field stays unknown. A news upload can contain archive footage or third-party inserts.
- **Reference:** [yt-dlp](https://github.com/yt-dlp/yt-dlp).

## Wikimedia Commons

- **Search:** public Action API, file namespace, media-type filtering, then file metadata. Current code uses `imageinfo` with URL, size, MIME type, `mediatype`, and `extmetadata`. Declared `VIDEO` is video. `BITMAP` and `DRAWING` are images. Declared `AUDIO`, office, text, executable, and other non-image/non-video types stay out even when the MIME looks familiar. When `mediatype` is absent, only a `video/` or `image/` MIME is accepted, so bare `application/ogg` stays out. The stored MIME remains the API value. A filename does not choose the kind.
- **Video detail:** search records the file from one `imageinfo` response and marks `videoinfo` absent. Resolving a video stores derivatives and `srclang` tracks on that candidate. Preview downloads the refreshed original file and does not copy that video detail onto the saved search candidate. Refresh returns the same detail on its copy. A failed or empty `videoinfo` response does not drop the file. Image derivatives are poster frames, not representations and not timestamps. The `derivatives` list can repeat the original file first, with no `transcodekey`, and the `src` may differ only by tracking query parameters. That file stays a single `original`. A row with `transcodekey` is a transcode and keeps that key. A video that is neither the original nor a transcode stays as a usable representation without an invented role. TimedMediaHandler tracks use `srclang`, `src`, `kind`, `type`, `label`, and `dir`. The candidate stores `srclang` as `commons.timed_text[].lang` and `src` as `url`, plus those fields when they are non-empty strings. `lang` and `language` remain aliases. A discovered track URL is not a downloaded or parsed caption, and no cue timings are stored. Malformed optional metadata leaves the original file URL in place.
- **Acquisition:** the selected representation is the file URL from `imageinfo`, for an image or a video. A transcode is recorded beside it and does not replace that file. The original may be WebM or another format rather than MP4. A timestamped thumbnail does not prove a server-side cut and is never copied into `media_url` or the segment.
- **Keep:** the file page, creator, exact license, attribution, and chosen representation. Unknown license stays unknown.
- **Reference:** [Commons API](https://commons.wikimedia.org/wiki/Commons:API/MediaWiki), [API:Imageinfo](https://www.mediawiki.org/wiki/API:Imageinfo), [MIME type detection](https://www.mediawiki.org/wiki/Manual:MIME_type_detection), [TimedMediaHandler API](https://www.mediawiki.org/wiki/Extension:TimedMediaHandler/API).

## Internet Archive / Archive.org

- **Search:** public catalog search, then `/metadata/{identifier}`. Restrict by media type, collection, subject, date, or creator when useful.
- **Critical distinction:** one item can contain several independent videos. Enumerate its files and identify the actual media asset; the item is not necessarily one film or one downloadable file.
- **Inside a video:** collect captions when present. Use a smaller proxy for exploration and a suitable high-quality representation for the selected interval. A catalog match does not supply shot boundaries automatically.
- **Access/acquisition:** public metadata is generally readable without login; restricted files require their own access check. Preserve item ID, file identity, and the canonical item page.
- **Keep:** item/asset provenance and rights. FedFlix or a collection name alone does not establish the rights of every included fragment.
- **Implemented slice:** `archive` search, actual file/representation selection, associated captions, restrictions, and resumable fragment chains use the common ledger and review route. A chain is one to five allowed catalogs. Each catalog has three meaningful queries. Confirmed suitable options carry across catalogs. One additional disjoint pass is allowed and a third pass is not. Suitable-option confirmation names the viewed preview or acquired file, groups identical stills and near-duplicate trims, and can keep several scenes of one source with `preview --option`. Three current distinct options stop later dispatches. An unassessed result or interrupted query on the current catalog blocks the additional pass and a shortfall until `search-assess`. Rejection leaves the count until a new visual confirmation; approval alone does not restore it. Catalogs without an implemented keyword-search route can be planned, and a query there is refused instead of invented. Browser attempts/import use the same budget. UN/Destockd preview references remain deferred until a separately acquired original is viewed and confirmed; the broader requested-original policy remains deferred. [Operational commands](GUIDE.md#provider--archiveorg-and-fragment-search).
- **References:** [search guide](https://archivesupport.zendesk.com/hc/en-us/articles/360018359991-Search-A-Basic-Guide), [Metadata API](https://archive.org/developers/metadata.html).

## NASA Image and Video Library

- **Search:** `https://images-api.nasa.gov/search`, using text and media type; resolve the selected `nasa_id` through `/asset/{nasa_id}`.
- **Access:** this media catalog does not require the general NASA developer API key. Current code supports images and video.
- **Acquisition:** inspect the asset list for an appropriate original/representation rather than using the search thumbnail as the final media. The asset API publishes `images-assets.nasa.gov` file hrefs as `http://`. `get_json` already rewrites that exact host, with no userinfo and no port, to `https://` while scrubbing the JSON, before it returns the body. Public URL validation and path encoding then see the HTTPS URL. Other HTTP hosts, credentials, and signed queries are rejected. The scheme change stays in that transport scrub and does not download or decode the file.
- **Keep:** creator/center, date, NASA ID, source page, and item conditions, including third-party authorship. The candidate stores those on `nasa`. `creator.name` is the third party when one is named, otherwise the center. Rights stay unknown; the item description is not permission evidence. The search thumbnail is the poster. The selected file comes from the asset list. When both a `~medium` and a `~orig` file are listed, the current selector keeps `~medium`. Search metadata may already give `https://` preview links on the same host; those stay posters.
- **References:** [API documentation](https://images.nasa.gov/docs/images.nasa.gov_api_docs.pdf), [media conditions](https://www.nasa.gov/nasa-brand-center/images-and-media/).

## Library of Congress

- **Search:** public JSON responses (`fo=json`), keyword query, and facets for format, collection, date, place, language, or contributor. Available full text can include video transcripts.
- **Acquisition:** inspect item resources and their actual file variants. Prefer the master/highest available quality, especially for maps and scans, rather than a small web derivative.
- **Known-card handoff:** observed metadata for a canonical item can enter `resolve --locator-metadata` without another search or blocked API call. It remains a manual locator until an actually obtained master is linked with `--original-for`. Both TIFF suffixes are supported. A dated supplied 5880×3049 TIFF passed decoding, preview and viewed confirmation on 2026-10-06; JSON API access remains unverified after browser-verification 403. See [QUALITY](QUALITY.md) for the separate evidence and limitations.
- **Inside a video:** use supplied timed captions or plain transcript text. The current adapter supports direct image/video files; HLS and unconfirmed Streaming Services operations remain unsupported/manual.
- **Keep:** item/resource identifiers, actual file, source page, date, and item-level rights/access statements.
- **References:** [APIs](https://www.loc.gov/apis/), [query parameters](https://www.loc.gov/apis/json-and-yaml/requests/parameters/).

## DVIDS

- **Search:** official Search API with an application key. Useful filters include video type, `B-Roll` category, branch, country, city, date, duration, and HD status.
- **Access:** search/read integration needs `DVIDS_API_KEY`. Optional `DVIDS_CLIENT_SECRET` is used as the documented server `api_key` without browser Referer; upload OAuth permissions are unnecessary.
- **Acquisition:** resolve the selected asset and available files; a search thumbnail is not the editing original.
- **Keep:** asset ID, unit/creator credit, capture date versus publication date, location, and usage conditions. Official footage may still be archival relative to the narrated event.
- **References:** [API access](https://api.dvidshub.net/docs), [Search API](https://api.dvidshub.net/docs/search_api).

## Europeana

- **Search:** Search API, then the selected record. Use the relevant collection, media type, date, place, and language metadata.
- **Access:** confirm the issued type in `EUROPEANA_KEY_TYPE`: `personal` for development experiments, `project` for operational use. Without this confirmation, the adapter refuses network access. Follow the current key terms for the intended application.
- **Acquisition:** inspect links to the holding institution and its media; a Europeana record does not guarantee a direct downloadable original. An actually obtained institution file can enter the common workflow with `resolve --file --original-for <Europeana-candidate> --original-conditions "<observed source/file conditions>"`. This retains record and fragment context with separate measured file/hash and rights gates; an API thumbnail or IIIF pointer is not an acquired original.
- **Keep:** Europeana ID, holding institution, original record/media link, creator/date, and the record's rights statement.
- **References:** [APIs](https://api.europeana.eu/en), [API keys](https://www.europeana.eu/en/how-to-register-for-and-manage-an-api-key).

## NARA

- **Search:** National Archives Catalog API using its required key, then record details and digital objects.
- **Access:** the implemented v2 adapter requires `NARA_API_KEY` and sends it in a private header. A dated search/object acquisition sample is recorded in [QUALITY.md](QUALITY.md); an earlier note about a missing key is not a permanent access verdict.
- **Acquisition:** inspect the actual digital files. Catalog API access/storage conditions and rights in a photograph or film are separate checks.
- **Keep:** catalog identifier, record/collection context, date, digital object, source page, and rights restrictions.
- **Reference:** [Catalog API](https://www.archives.gov/research/catalog/help/api).

## Pexels

- **Search:** Pexels video API with `PEXELS_API_KEY`. The adapter searches video only. `search --media image` returns an explicit refusal and does not call the API. Search responses are not cached for a day.
- **Acquisition:** select an MP4 at or below 1920 pixels on the long side and refresh the asset by ID before preview or final acquisition. Refresh replaces the file URL and the reported width, height, and duration, and it keeps approval and the selected interval. `video_pictures[].nr` is not a video second.
- **Use:** a saved hit is `stock: true` and `match.kind: illustrative`, including when the command was asked for a literal intent. That mark is not visual confirmation and not reuse permission. Illustrative atmosphere/context still requires the project's stock policy.
- **Keep:** creator, asset ID/page, real dimensions, and Pexels license/API conditions.
- **Reference:** [API documentation](https://www.pexels.com/api/documentation/).

## Pixabay

- **Search:** video API with `PIXABAY_API_KEY`; search and id refresh use a 24-hour cache. Photo search is not implemented. `search --media image` is refused and does not call the API.
- **Acquisition:** resolve by ID and choose the actual video variant. Refresh copies the new URL and reported dimensions and keeps approval and the interval. Respect request limits and restrictions on mass downloading.
- **Use/keep:** a saved hit is `stock: true` and `match.kind: illustrative`. That is stock policy, not visual confirmation or reuse permission. Record creator, source page, dimensions, and usage conditions. The selected variant's thumbnail is a poster. A preview-image sequence number is not a known video second without an explicit mapping.
- **Reference:** [API documentation](https://pixabay.com/api/docs/).

## Mapillary

Implemented geographic image search and original refresh enter the [common workflow](GUIDE.md#providers--mapillary-telegram-and-x-access). Topic labels alone cannot dispatch; only normalized geography/media/date changes create another geographic query. A dated acquired street panorama passed technical decoding but was visually unsuitable for the named square. This does not establish complete place coverage or reuse rights.

- **Search:** geographic/bounding-box search using a client token. Supply a real location or coordinates; generic topic keywords alone are insufficient for the retained route.
- **Result:** street-level images of a place, not a general source of moving footage.
- **Keep:** image/sequence ID, coordinates, capture date, creator, source link, and applicable conditions. Confirm the image actually shows the requested place.
- **Reference:** [API examples](https://github.com/mapillary/api-demo/blob/main/README.md).

## Telegram via Telethon

Implemented optional Telethon route uses local interactive login/2FA, an explicit public whitelist, date bounds, saved cursor/results and bounded FloodWait recovery through the [existing CLI](GUIDE.md#providers--mapillary-telegram-and-x-access). Metadata and fixture success do not establish an authorized live session or acquisition. Signed/session material and private forwarded peer details do not enter public provenance.

- **Search:** bounded history/text search within an explicit whitelist of public channels, using `api_id`, `api_hash`, and an authorized user session.
- **Scope from prior research:** a whitelist was derived from a selected channel folder. Preserve an explicit channel list for this project; authorization does not mean access to all subscriptions or private conversations is in scope.
- **Acquisition:** inspect the selected message and its attachments. Preserve channel, message ID/permalink, timestamp, caption, and attachment identity; reposts need original-source verification.
- **Limits:** store a cursor and avoid repeatedly reading unchanged messages. Handle short FloodWaits within the run; record longer waits as the next eligible access time and continue with other sources.
- **Privacy:** keep credentials and session files private; reports contain public provenance, not session material.
- **References:** [application credentials](https://core.telegram.org/api/obtaining_api_id), [Telethon errors and limits](https://docs.telethon.dev/en/stable/concepts/errors.html).

## GDELT TV

Implemented as `gdelt_tv` with shared planned-query accounting and explicit Archive/local original linking. See [commands](GUIDE.md#providers--gdelt-tv-ec-audiovisual-and-un-web-tv). A 2026-10-04 StationDetails observation reports CNN coverage from 2009-07-02 through 2024-10-10. This dated range is queried and retained per station; it is not a universal GDELT limit. No visual route is implemented. The historical sample's Archive files require separate access.

- **Search:** public TV API for finding a broadcast segment and temporal reference.
- **Result:** a locator. Treat caption-based matches and any visual/AI search route as separate capabilities with their own actual channel/date coverage.
- **Acquisition:** establish where the underlying broadcast can be viewed and obtained. A search hit is not a promise of a downloadable or cleared editing file.
- **Keep:** broadcaster/program, broadcast time, matching text or evidence, locator URL, and the eventual media source.
- **Reference:** [TV API](https://blog.gdeltproject.org/gdelt-2-0-television-api-debuts/).

## X

- **Retained route:** bounded CLI discovery through native `x_search` using the previously agreed Grok OIDC mode. The current client's selected `grok-4.7` pair, expiry/refresh, installed version and proxy headers are validated without switching model, account mode or API billing. One native call per request shares planned query limits; completed results can replay/resume without another inference. Other selected models stay unverified. `x-access` remains local diagnostics without inference or refresh. See [commands](GUIDE.md#providers--mapillary-telegram-and-x-access) and the dated [CLI/media observation](archive/quality-evidence-through-2026-10-07.md#catalog-acceptance-follow-up--2026-10-05-2132-candidate).
- **Search:** use supported account/date filters and preserve the post URLs returned. Confirm exact quotations against the original post.
- **Acquisition:** original-post retrieval, screenshot capture, and media download are separate operations. X Search is not a downloader; Grok OAuth does not substitute for credentials of a separate X API integration.
- **Access:** verify supported model/tool, login, expiry, and refresh/re-login independently. Preserve the chosen OAuth mode rather than silently switching to API billing or a different model. Provider subscription limits still apply.
- **Keep:** original post/account identity and citation evidence; search-reported date, original language and excerpts remain explicitly unverified until original viewing. Attached-media identity stays unknown until a separately verified operation establishes it. One public sample was viewed in the browser, acquired separately with yt-dlp and explicitly imported; this does not enable automatic remote X media acquisition. Keep translations and styled quotation cards separate from the original.
- **Reference:** [xAI X Search](https://docs.x.ai/developers/tools/x-search). The subscription/OAuth route above is retained from project-specific research, not established solely by the public API guide.

## EC Audiovisual Service

**Provider ID:** `ec_audiovisual`. Implemented in this checkout with bounded public discovery, exact-shot identity and existing review/acquisition gates. The primary client/schema and a selected decoded MP4 were revalidated on 2026-10-04; see [commands](GUIDE.md#providers--gdelt-tv-ec-audiovisual-and-un-web-tv) and [evidence](QUALITY.md). Fallback and HLS paths have offline coverage; live fallback/HLS acquisition remain unverified.

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
- CLI: `--media video` searches shots then videos, `--media image` searches `PHOTO`/`REPORTAGE`, and `any` allows all four. `--catalog-filter type=VIDEO` selects whole recordings. Keywords use the client parameter `kwgg`; `q` does not filter this endpoint.
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

Implemented with shared locale/query accounting, public timed-transcript inspection and separate player metadata checks. The dated sample passed transcript discovery and yt-dlp player inspection; the separately authorized 1908–1911s working window was acquired and decoded at 1280×720. This does not establish acquisition of the full source or a cleared editing original. See [commands](GUIDE.md#providers--gdelt-tv-ec-audiovisual-and-un-web-tv) and [dated evidence](archive/quality-evidence-through-2026-10-07.md#remaining-catalog-reconciliation--2026-10-06-2133-candidate).

- **Full-text route:** public UN Transcripts search; use `ft=1` to search transcript content rather than only meeting titles:

  ```text
  https://transcripts.un.org/en/meetings.json?q=QUERY&ft=1
  ```

- API read endpoints require no authentication. Select the supported locale/language for the requested transcript; the documented locales include `en`, `fr`, `es`, `ar`, `zh`, and `ru`.
- **Coverage:** meeting search covers the last 365 days. For older events, use the Web TV catalog or a direct `webtv.un.org/en/asset/...` URL/asset ID. Empty transcript search is incomplete coverage, not proof that no recording exists. A sitemap can discover URLs but is not full-text speech search.
- **Inside a meeting:** retain matching text, speaker, date, language, and source timing; canonical/deep links with `?t=` point to the spoken moment. The transcripts are generated automatically and are not official UN records.
- **Acquisition:** after selection, check actual representations through yt-dlp on the public Web TV page; the retained route uses its Kaltura player. Working acquisition prefers identified video HLS with the page-locale audio track before the existing direct-file fallback. An advertised MP4 resolution does not prove it contains video. Preserve the canonical page, not an expiring signed stream URL. Keep the candidate visible for an explicit access decision before acquisition, independently of rights and human approval.
- **High-quality original:** refer to UN Audiovisual Library when the available Web TV representation is insufficient.
- **References:** [Transcripts API](https://github.com/united-nations/transcripts/blob/main/docs/api.md), [Web TV](https://webtv.un.org/), [UN media services](https://media.un.org/en/about-us).

## UN Audiovisual Library

**Retained provider ID:** `un_avlibrary`. This is an implemented browser/import archive locator and explicit supplied-original route. See [commands](GUIDE.md#browser-attempts-and-archive-locators).

**Dated working-preview evidence (2026-10-06, 2.13.4):** direct Asset ID plus observed card metadata reached yt-dlp inspection, acquired/viewed 22–25s Kaltura preview, Storyboard and successful window decoding for `d2313786` (960×540). Known cards can import their metadata without claiming a browser search; public canonical-card players remain preview references. Original/request availability, original timing, reuse rights and human approval remain separate. This sample does not establish working playback for other legacy players.

- **Search/access:** website discovery, public cards, and direct URL/Asset ID. The supplied research found no universal public search API; do not invent one.
- **Keep:** title, date, description, preview reference, shotlist/time markers when available, asset ID, and the footage-request link.
- **Acquisition:** a candidate marked `license_required` remains useful and visible. Public preview is a viewing reference, not a cleared editing original. The user requests the selected asset/interval; import the officially supplied file together with its conditions.
- **Rights:** UN archive footage is not public domain. Authorization/license agreement and possible fees apply under the library's published guidelines.
- **UNifeed:** retained as a UN news-service variant, not an independently confirmed provider ID in the supplied inventory.
- **References:** [guidelines](https://media.un.org/avlibrary/en/guidelines), [request footage](https://media.un.org/avlibrary/en/contact/request_footage).

## Destockd

**Retained provider ID:** `destockd`. Its value is the division of FedFlix films into individual shots. The current browser/import route shares fragment accounting; see [commands](GUIDE.md#browser-attempts-and-archive-locators).

- **Initial route:** search the website and import the direct shot link; retain film title and shot ID.
- **Special access finding:** the supplied research records `Disallow: /api/` in `robots.txt`. The discovered JSON API is undocumented. Preserve website/link import until the operator agrees to a programmatic access method and request rate; the robots finding was not re-probed for this document.
- **Shot detail:** preview, exact boundaries, and the source-film link can be visible in the UI, but cannot be inferred from the hash-route URL. Missing values remain unknown.
- **After agreed API access:** bounded read-only requests, cache, and schema checks; keep manual import as fallback. Whole-catalog crawling and protection bypass are outside the retained route.
- **Acquisition:** connect the shot to its original film through Archive.org when the metadata/link is available. Preserve Destockd shot ID and Archive.org item/file identity separately. The current CLI imports observed public previews and links a matching selected Archive original with `resolve --original-for`; boundaries remain unknown unless actually observed.
- **Rights:** verify the actual original and third-party inserts; a general “public domain or unrestricted” label is not sufficient item evidence.
- **References:** [website](https://destockd.com/), [robots.txt](https://destockd.com/robots.txt).

## Instagram

- **Discovery:** agent-operated browser search/profile browsing in an authorized session. There is no global Instagram keyword search in the current CLI.
- **Optional external search route:** Agent Reach documents OpenCLI user search, profiles, recent posts, and Explore through an existing logged-in Chrome session. This is an integration option, not installed get-brolls functionality or proof of full-content keyword search.
- **Current acquisition route:** browser/Playwright → capture video and audio representations of the same Reel → private temporary configs → pair collector/curl → FFmpeg merge → ffprobe/full decoding. yt-dlp by full post URL is another route when it works for the item.
- **Critical pairing:** match Reel ID/manifest/asset identity and duration. Preloaded recommendations may supply unrelated streams; the first two MP4 requests are not sufficient evidence. `blob:` is not a downloadable source URL.
- **Fragment handoff:** reserve before browser discovery, import the observed canonical Reel, then link the collector MP4 with `resolve --original-for` and matching `--source-url`/observed pair conditions. A bounded 2026-10-06 sample completed capture, pairing, merge, full decoding, inspect, viewed preview and common review; human approval/rights remain separate.
- **Keep:** canonical Reel URL, account, caption/context/date, and selected representation. Signed CDN URLs/configs remain private and may need recapture after expiry. The capture tool must actually expose the required responses; the pair collector does not discover them itself.
- **References:** [current browser/acquisition procedure](GUIDE.md#instagram--navegadorplaywright-dois-streams-e-mp4), [Agent Reach access option](https://github.com/Panniantong/Agent-Reach/blob/main/docs/README_en.md#supported-platforms).

## TikTok

- **Discovery:** browser → complete canonical `https://www.tiktok.com/@USER/video/ID` URL. Resolve shortened links first. The current CLI has no global TikTok keyword search.
- **Dated working sample:** on 2026-10-06, reserved browser discovery/import and yt-dlp with pinned `curl-cffi` obtained a decoded 7.5–10.5s city-panorama window, measured 576×1024. This proves that selected route/sample, not future access, the whole source, editorial acceptance or reuse rights.
- **Profile discovery detail:** the current guide records `https://www.tiktok.com/embed/@USER` as a way to discover recent post IDs when the ordinary logged-out profile grid is empty or challenged. Check this route for the actual profile; it is not a guaranteed universal bypass or a global search API.
- **Acquisition:** yt-dlp on the full post URL; resolve gathers title, handle, creator, and duration when the metadata request succeeds. Individual posts may require a session or be inaccessible.
- **Keep:** post ID, canonical page, account, date/context, source language, and conditions. A discovered embed/post address is not reuse authorization.
- **Reference:** [current TikTok procedure](GUIDE.md#provedor--tiktok).

## Shared catalog result information

Keep the canonical page and original item/asset ID, source date/location/creator, actual media representation, and any known interval or provider timing. Separate discovery, preview, technical acquisition, reuse conditions, and human acceptance. A manual/license-required candidate remains visible with its acquisition method. Record actual search coverage and access errors so a limited or failed search is not reported as absence of footage.

Local files are an import route rather than another catalog. Import them with their source provenance under the existing guide. Coverr and Unsplash were explicitly excluded in the supplied final source inventory and are not added to this reference's target catalog list.

## Integration design

The accepted [fragment-specific search chain planning decision](adr/0001-fragment-catalog-search-chain.md) records the search behavior and an integrated rollout covering the complete target inventory. [CONTEXT.md](../CONTEXT.md) defines its domain terms; neither document establishes additional implemented provider capabilities. LoC, DVIDS, Europeana and NARA join the common route with [explicit original selection and access/filter requirements](GUIDE.md#providers--loc-dvids-europeana-and-nara). GDELT TV, EC Audiovisual and UN Web TV have implemented bounded adapters. Mapillary geographic images and Telegram's optional public-whitelist user-session route are implemented. Bounded native X discovery through retained Grok OIDC and `grok-4.7` has dated live evidence; original references/local captures have their own supported entry. Browser/locator limits and dated live evidence remain separate from implementation.

The accepted [catalog integration specification](SPEC-CATALOG-INTEGRATION.md) defines implementation contracts and offline/live acceptance checks for this scope.

YouTube, Wikimedia Commons, NASA, Pexels, and Pixabay share Archive's implemented bounded fragment commands and catalog chains: `search-plan`, `search --planned`, preview, `search-confirm`, and `search-assess`. Stills use the measured poster. Planned Pexels and Pixabay hits stay stock and illustrative. Planned photo search on YouTube and the stock banks is refused before a query is spent. One additional disjoint chain is supported. The retained browser/locator routes use the shared reservation/import contract rather than universal keyword APIs. Dated samples and current operational limits are summarized in [QUALITY.md](QUALITY.md), with full reports in its archive; completed engineering criteria are recorded in the [acceptance checkpoint](CATALOG-ACCEPTANCE.md).
