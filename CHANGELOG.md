## 0.11.1

- Feature: Install from git URL ([!152](https://gitlab.com/leaf-framework/leaf/-/merge_requests/152))
- Feature: Organisation and department tags ([!154](https://gitlab.com/leaf-framework/leaf/-/merge_requests/154))
- Removed: unused code, including `MeasurementHandler` and `DBWatcher`. ([!153](https://gitlab.com/leaf-framework/leaf/-/merge_requests/153))
- Patch: `leaf --help` gives the right default port, 4242. ([!153](https://gitlab.com/leaf-framework/leaf/-/merge_requests/153))
- Patch: the Docker image installs LEAF from PyPI. ([!153](https://gitlab.com/leaf-framework/leaf/-/merge_requests/153))
- Patch: the pipeline creates the GitLab release page again. ([!151](https://gitlab.com/leaf-framework/leaf/-/merge_requests/151))

## 0.11.0

- Feature: Control results ([!145](https://gitlab.com/leaf-framework/leaf/-/merge_requests/145), [!146](https://gitlab.com/leaf-framework/leaf/-/merge_requests/146), [!148](https://gitlab.com/leaf-framework/leaf/-/merge_requests/148))
- Feature: Disable adapter install ([!144](https://gitlab.com/leaf-framework/leaf/-/merge_requests/144))
- Feature: Restricted adapters ([!149](https://gitlab.com/leaf-framework/leaf/-/merge_requests/149))
- Removed: the KEYDB output; use `FILE` or `SQL` as the fallback. ([!147](https://gitlab.com/leaf-framework/leaf/-/merge_requests/147))
- Removed: influxobject; adapters use leafobject (`LeafPoint`) instead. ([!146](https://gitlab.com/leaf-framework/leaf/-/merge_requests/146))
- Patch: three tests that failed at random on slow CI runners. ([!150](https://gitlab.com/leaf-framework/leaf/-/merge_requests/150))

## 0.10.25

- Patch: publishing to PyPI falls back to a token. ([!143](https://gitlab.com/leaf-framework/leaf/-/merge_requests/143))

## 0.10.24

- Patch: the publish job shows why PyPI refused it. ([!142](https://gitlab.com/leaf-framework/leaf/-/merge_requests/142))

## 0.10.23

- Feature: Controlling equipment ([!129](https://gitlab.com/leaf-framework/leaf/-/merge_requests/129))
- Feature: Control tab ([!134](https://gitlab.com/leaf-framework/leaf/-/merge_requests/134))
- Feature: Monitoring plot ([!133](https://gitlab.com/leaf-framework/leaf/-/merge_requests/133), [!137](https://gitlab.com/leaf-framework/leaf/-/merge_requests/137), [!140](https://gitlab.com/leaf-framework/leaf/-/merge_requests/140))
- Feature: Web interface password ([!136](https://gitlab.com/leaf-framework/leaf/-/merge_requests/136))
- Feature: Notarised macOS installer ([!126](https://gitlab.com/leaf-framework/leaf/-/merge_requests/126))
- Feature: Adapter help ([!131](https://gitlab.com/leaf-framework/leaf/-/merge_requests/131))
- Patch: the HTTP watcher no longer drops responses without caching headers. ([!138](https://gitlab.com/leaf-framework/leaf/-/merge_requests/138))
- Patch: `control: true` starts again. ([!132](https://gitlab.com/leaf-framework/leaf/-/merge_requests/132))
- Patch: errors are published once, including failed commands from the Control tab. ([!139](https://gitlab.com/leaf-framework/leaf/-/merge_requests/139))
- Patch: the desktop launcher stays responsive during install. ([!128](https://gitlab.com/leaf-framework/leaf/-/merge_requests/128))
- Patch: Restart and Stop moved to the header, behind a confirmation. ([!131](https://gitlab.com/leaf-framework/leaf/-/merge_requests/131))
- Patch: measurements are published under their own metric topic instead of `…/unknown`. ([!133](https://gitlab.com/leaf-framework/leaf/-/merge_requests/133))
- Patch: dependencies updated to clear known vulnerabilities. ([!141](https://gitlab.com/leaf-framework/leaf/-/merge_requests/141))
- Patch: images are published to Harbor. ([!135](https://gitlab.com/leaf-framework/leaf/-/merge_requests/135))

## 0.10.22

- Patch: the Linux installers build again. ([!125](https://gitlab.com/leaf-framework/leaf/-/merge_requests/125))

## 0.10.21

- Feature: Signed Windows installer ([!123](https://gitlab.com/leaf-framework/leaf/-/merge_requests/123), [!124](https://gitlab.com/leaf-framework/leaf/-/merge_requests/124))
- Patch: each equipment instance publishes its own heartbeat, every 300 s; `heartbeat_topic` is no longer used.
- Patch: installing an adapter no longer blocks the web interface.
- Patch: a release is made by pushing a version tag. ([!122](https://gitlab.com/leaf-framework/leaf/-/merge_requests/122))

## 0.10.20

- Removed: the unused MockFunctionalAdapter marketplace entry. ([!121](https://gitlab.com/leaf-framework/leaf/-/merge_requests/121))

## 0.10.19

- Patch: nicegui and requests updated. ([!120](https://gitlab.com/leaf-framework/leaf/-/merge_requests/120))

## 0.10.18

- Patch: the MQTT watcher no longer misses messages right after it starts.

## 0.10.12

- Patch: leaner release pipeline.

## 0.10.16

- Patch: heartbeats are no longer replayed from the fallback.

## 0.10.15

- Feature: Update check ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))
- Feature: LADS watcher ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))
- Feature: Compressed FILE output ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))
- Patch: polling watchers keep running after an error. ([!118](https://gitlab.com/leaf-framework/leaf/-/merge_requests/118))
- Patch: MQTT is the default output again. ([!119](https://gitlab.com/leaf-framework/leaf/-/merge_requests/119))

## 0.10.14

- Patch: CI reports the real test coverage. ([!116](https://gitlab.com/leaf-framework/leaf/-/merge_requests/116), [!117](https://gitlab.com/leaf-framework/leaf/-/merge_requests/117))

## 0.10.13

- Patch: the first messages after startup no longer go to the fallback. ([!113](https://gitlab.com/leaf-framework/leaf/-/merge_requests/113))
- Patch: `+` and `#` in topics no longer make an adapter restart in a loop. ([!115](https://gitlab.com/leaf-framework/leaf/-/merge_requests/115))
- Patch: a shared FILE fallback no longer gets corrupted. ([!115](https://gitlab.com/leaf-framework/leaf/-/merge_requests/115))
- Patch: lint and tests run in CI again. ([!114](https://gitlab.com/leaf-framework/leaf/-/merge_requests/114))

## 0.10.11

- Patch: the FILE output creates its folder if needed. ([!108](https://gitlab.com/leaf-framework/leaf/-/merge_requests/108))
- Patch: old patch releases are pruned after a new one. ([!112](https://gitlab.com/leaf-framework/leaf/-/merge_requests/112))

## 0.10.6

- Feature: Generator measurements ([!107](https://gitlab.com/leaf-framework/leaf/-/merge_requests/107))

## 0.10.5

- Patch: a malformed configuration shows a clear error.

## 0.10.4

- Patch: empty configuration sections no longer crash LEAF.

## 0.10.3

- Patch: reinstalling an adapter fetches its latest version.

## 0.10.2

- Patch: measurements received over MQTT go to the right topic.

## 0.10.0

- Patch: the Windows ARM64 installer builds.

## 0.10.1

- Feature: Desktop installers
