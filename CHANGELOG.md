# Changelog

What changed in each LEAF release from 0.10 onwards, newest first. Releases are listed in the order they were
made, which differs from the version order in two places: 0.10.12 was tagged after 0.10.16, and 0.10.1 before
0.10.0. Versions 0.10.7–0.10.10 and 0.10.17 were never released.

## 0.11.1

### Added
- **Install from git URL** in the Adapters tab, for adapters that are not in the marketplace, with an optional username and token for private repositories. Only http(s) URLs; a token is only sent over https. ([!152](https://gitlab.com/leaf-framework/leaf/-/merge_requests/152))
- Every measurement and control result carries `organisation` and `department` tags from the instance configuration, so OAK can store data from adapters that never set them. An adapter's own tags win, with a warning when they differ from the configuration. ([!154](https://gitlab.com/leaf-framework/leaf/-/merge_requests/154))

### Removed
- Unused code: `MeasurementHandler`, `DBWatcher` (it only raised `NotImplementedError`) and a few unused helpers and constants. ([!153](https://gitlab.com/leaf-framework/leaf/-/merge_requests/153))

### Fixed
- `leaf --help` said the default port is 8080; it is 4242. ([!153](https://gitlab.com/leaf-framework/leaf/-/merge_requests/153))
- The Docker image installed LEAF from an old GitLab group; it now installs `leaf-framework` from PyPI. ([!153](https://gitlab.com/leaf-framework/leaf/-/merge_requests/153))
- The GitLab release page is created again by the pipeline; since 0.10.23 the job failed on one of the runners. ([!151](https://gitlab.com/leaf-framework/leaf/-/merge_requests/151))

## 0.11.0

### Breaking
- **The KEYDB output is removed**, with redis and aioredis. A configuration that uses `KEYDB` no longer loads; use `FILE` or `SQL` as the fallback instead. ([!147](https://gitlab.com/leaf-framework/leaf/-/merge_requests/147))
- LEAF depends on **leafobject** (`LeafPoint`) instead of influxobject (`InfluxPoint`). Adapters that import influxobject need `leafobject` instead. ([!146](https://gitlab.com/leaf-framework/leaf/-/merge_requests/146))

### Added
- **Control results**: every control command, from MQTT or the Control tab, applied or rejected, is published on `…/control/result` as a LeafPoint with the tags `source`, `status` and, for a rejection, `error`. ([!145](https://gitlab.com/leaf-framework/leaf/-/merge_requests/145), [!146](https://gitlab.com/leaf-framework/leaf/-/merge_requests/146), [!148](https://gitlab.com/leaf-framework/leaf/-/merge_requests/148))
- **`LEAF_DISABLE_ADAPTER_INSTALL`** switches off installing and uninstalling adapters from the web interface, for shared deployments where adapters come from the image. ([!144](https://gitlab.com/leaf-framework/leaf/-/merge_requests/144))
- **Restricted adapters**: marketplace entries with `access: restricted` install with a username and token handed out per user, with a "Request access" link. RAMSMART is the first. ([!149](https://gitlab.com/leaf-framework/leaf/-/merge_requests/149))

### Fixed
- Three tests that failed at random on slow CI runners. ([!150](https://gitlab.com/leaf-framework/leaf/-/merge_requests/150))

## 0.10.25

### Fixed
- Publishing to PyPI falls back to a token when PyPI refuses trusted publishing. ([!143](https://gitlab.com/leaf-framework/leaf/-/merge_requests/143))

## 0.10.24

### Fixed
- The publish job shows PyPI's reason when it refuses to publish. ([!142](https://gitlab.com/leaf-framework/leaf/-/merge_requests/142))

## 0.10.23

### Added
- **Controlling equipment**: an adapter with a `controller.py` can be steered over MQTT on `…/control` when its instance has `control: true`. ([!129](https://gitlab.com/leaf-framework/leaf/-/merge_requests/129))
- **Control tab**, built from the controls an adapter declares in its `device.json`. LEAF checks every control message against them and against the instance's `control_limits` before the controller sees it. ([!134](https://gitlab.com/leaf-framework/leaf/-/merge_requests/134))
- **Monitoring plot**: latest-value tiles and a time plot per metric, with a separate series per entity and tiles grouped per instance, and *Add all* / *Clear all* for the metric picker. ([!133](https://gitlab.com/leaf-framework/leaf/-/merge_requests/133), [!137](https://gitlab.com/leaf-framework/leaf/-/merge_requests/137), [!140](https://gitlab.com/leaf-framework/leaf/-/merge_requests/140))
- **`LEAF_UI_PASSWORD`** puts the web interface behind a login with a 30-day session. ([!136](https://gitlab.com/leaf-framework/leaf/-/merge_requests/136))
- The macOS installer is signed and notarised, so Gatekeeper opens it without warnings. ([!126](https://gitlab.com/leaf-framework/leaf/-/merge_requests/126))
- An adapter's packaged `README.md` is shown as help in the Configuration tab. ([!131](https://gitlab.com/leaf-framework/leaf/-/merge_requests/131))

### Changed
- Restart and Stop moved to the header, behind a confirmation. ([!131](https://gitlab.com/leaf-framework/leaf/-/merge_requests/131))
- LeafPoints are published under their own metric topic; they used to land on `…/unknown`. ([!133](https://gitlab.com/leaf-framework/leaf/-/merge_requests/133))
- Dependencies raised to clear known vulnerabilities: nicegui 3.18, pillow 13, watchdog 7, dateparser 1.4, cairosvg 2.9. ([!141](https://gitlab.com/leaf-framework/leaf/-/merge_requests/141))
- LEAF is published to PyPI with trusted publishing and provenance attestations, and its images go to Harbor. ([!135](https://gitlab.com/leaf-framework/leaf/-/merge_requests/135))

### Fixed
- `HTTPWatcher` dropped every response from servers that send no ETag or Last-Modified header, so the IndPenSim adapter published nothing. ([!138](https://gitlab.com/leaf-framework/leaf/-/merge_requests/138))
- `control: true` could not start, because the configured MQTT output was not recognised as one. ([!132](https://gitlab.com/leaf-framework/leaf/-/merge_requests/132))
- Failed commands from the Control tab are reported on the error topic, and each error is published once instead of once per process. ([!139](https://gitlab.com/leaf-framework/leaf/-/merge_requests/139))
- The desktop launcher's progress window stays responsive on macOS and Windows during install. ([!128](https://gitlab.com/leaf-framework/leaf/-/merge_requests/128))

## 0.10.22

### Fixed
- The Linux installers build again after Debian moved the bullseye packages to its archive. ([!125](https://gitlab.com/leaf-framework/leaf/-/merge_requests/125))

## 0.10.21

### Changed
- **Heartbeat per instance**: every equipment instance publishes a retained heartbeat on `…/<instance_id>/heartbeat`, every 300 s by default (`heartbeat_interval`, `0` turns it off). The single `heartbeat_topic` and its last will are gone; `heartbeat_topic` is ignored with a warning.
- Installing an adapter from the web interface no longer blocks the interface.
- Releases are made by pushing a version tag instead of on every merge to main. ([!122](https://gitlab.com/leaf-framework/leaf/-/merge_requests/122))

### Added
- The Windows installer, launcher and uninstaller are signed. ([!123](https://gitlab.com/leaf-framework/leaf/-/merge_requests/123), [!124](https://gitlab.com/leaf-framework/leaf/-/merge_requests/124))

## 0.10.20

### Removed
- The unused MockFunctionalAdapter marketplace entry. ([!121](https://gitlab.com/leaf-framework/leaf/-/merge_requests/121))

## 0.10.19

### Changed
- nicegui 3.16 and requests 2.34, installed from the committed lock file. ([!120](https://gitlab.com/leaf-framework/leaf/-/merge_requests/120))

## 0.10.18

### Fixed
- `MQTTEventWatcher` could miss messages published between `start()` and its subscriptions being in place; it now waits for the broker to confirm them.

## 0.10.12

### Changed
- Release pipeline: installers are no longer kept twice, and pruning old releases fails loudly.

## 0.10.16

### Fixed
- Heartbeats are no longer stored in the fallback and replayed later as a stale "alive".

## 0.10.15

### Added
- **Update check**: the web interface looks for a newer LEAF one hour after start, then weekly, and offers *Update & Restart*. Installs that did not come from PyPI are told about a release but never updated. `LEAF_DISABLE_UPDATE_CHECK=1` turns it off. ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))
- **LADS watcher** for OPC UA lab-device servers, which finds the variables to monitor itself. ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))
- The FILE output writes gzip when its filename ends in `.gz`. ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))

### Fixed
- Polling watchers (including Modbus) stopped for good after a single error, so an experiment silently stopped reporting; they now log it and keep polling. ([!118](https://gitlab.com/leaf-framework/leaf/-/merge_requests/118))
- MQTT is the default output in the bundled configuration again. ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))

## 0.10.14

### Fixed
- CI reports real test coverage. ([!116](https://gitlab.com/leaf-framework/leaf/-/merge_requests/116), [!117](https://gitlab.com/leaf-framework/leaf/-/merge_requests/117))

## 0.10.13

### Fixed
- At startup, LEAF waits briefly for the MQTT connection before falling back, so the first messages are no longer sent to the fallback. ([!113](https://gitlab.com/leaf-framework/leaf/-/merge_requests/113))
- Characters MQTT doesn't allow in topics (`+`, `#`) are removed before publishing, instead of making the adapter restart in a loop. ([!115](https://gitlab.com/leaf-framework/leaf/-/merge_requests/115))
- Concurrent adapters no longer corrupt a shared FILE fallback. ([!115](https://gitlab.com/leaf-framework/leaf/-/merge_requests/115))
- Lint and tests run in CI again. ([!114](https://gitlab.com/leaf-framework/leaf/-/merge_requests/114))

## 0.10.11

### Fixed
- The FILE output creates missing parent folders of its file. ([!108](https://gitlab.com/leaf-framework/leaf/-/merge_requests/108))

### Changed
- Older patch releases of the same minor version are pruned after a new release. ([!112](https://gitlab.com/leaf-framework/leaf/-/merge_requests/112))

## 0.10.6

### Added
- An interpreter's `measurement()` can be a generator (`yield`), so one call can produce many results without building them all in memory. ([!107](https://gitlab.com/leaf-framework/leaf/-/merge_requests/107))

## 0.10.5

### Fixed
- A malformed configuration shows a clear error instead of a traceback.

## 0.10.4

### Fixed
- An empty `OUTPUTS` or `EQUIPMENT_INSTANCES` section no longer crashes LEAF.

## 0.10.3

### Fixed
- Reinstalling an adapter always fetches its latest commit.

## 0.10.2

### Fixed
- Measurements received over MQTT are published under their metric.

## 0.10.0

### Fixed
- Windows ARM64 installer: wheels without a prebuilt ARM64 version are built from source.

## 0.10.1

### Added
- **Desktop installers** for macOS, Linux and Windows, which set up their own Python on first launch.
