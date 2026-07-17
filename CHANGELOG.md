# Changelog

## [0.2.1](https://github.com/chrismcdev/PeakRDL-check/compare/v0.2.0...v0.2.1) (2026-07-17)


### Bug Fixes

* **action:** compile once per file, cap annotations and job summary ([#14](https://github.com/chrismcdev/PeakRDL-check/issues/14)) ([0bad1be](https://github.com/chrismcdev/PeakRDL-check/commit/0bad1be068a9dca2bc343807ab1052563e843b93))
* **viewer:** load large change sets quickly and reliably ([#13](https://github.com/chrismcdev/PeakRDL-check/issues/13)) ([1b62333](https://github.com/chrismcdev/PeakRDL-check/commit/1b623335979520ee20b0e61aecb13b3303600849))


### Documentation

* clarify core commands and review workflows ([#11](https://github.com/chrismcdev/PeakRDL-check/issues/11)) ([c47d742](https://github.com/chrismcdev/PeakRDL-check/commit/c47d742339b0b6e1beaf88afadd9809720cb4212))

## [0.2.0](https://github.com/chrismcdev/PeakRDL-check/compare/v0.1.1...v0.2.0) (2026-07-14)


### Features

* **viewer:** improve review workflow ([#7](https://github.com/chrismcdev/PeakRDL-check/issues/7)) ([8dc9643](https://github.com/chrismcdev/PeakRDL-check/commit/8dc964336a3154897785e3deb253d550a0806611))


### Documentation

* remove internal planning and legacy runtime references ([#10](https://github.com/chrismcdev/PeakRDL-check/issues/10)) ([cdd8aaa](https://github.com/chrismcdev/PeakRDL-check/commit/cdd8aaaa50aacc1bc7e4ecf08f7c85e7f8c1b068))
* remove logo ([#8](https://github.com/chrismcdev/PeakRDL-check/issues/8)) ([5b40df6](https://github.com/chrismcdev/PeakRDL-check/commit/5b40df65134463e081e45f937ebdacf038ee9d4e))

## [0.1.1](https://github.com/chrismcdev/PeakRDL-check/compare/v0.1.0...v0.1.1) (2026-07-13)


### Bug Fixes

* **action:** use Node.js 24 action runtimes ([#6](https://github.com/chrismcdev/PeakRDL-check/issues/6)) ([61c8a65](https://github.com/chrismcdev/PeakRDL-check/commit/61c8a65e8680c7bfae29c103ee462d86f34e42eb))


### Documentation

* update issue templates ([#4](https://github.com/chrismcdev/PeakRDL-check/issues/4)) ([e26f839](https://github.com/chrismcdev/PeakRDL-check/commit/e26f8397735758b30c19958173b58c7c2d824ed7))

## 0.1.0 (2026-07-13)


### Features

* **build:** incremental build system with equivalence verification ([94d7885](https://github.com/chrismcdev/PeakRDL-check/commit/94d788596645fee7cfc16404cf5b96347f6ee9c1))
* **ci:** require unit tests ([ba04a07](https://github.com/chrismcdev/PeakRDL-check/commit/ba04a075135a35a9e946d38d7f2f55f2ff65d2a4))
* **cli:** doctor/cache/benchmark commands, test suite, mutation harness, GitHub Action ([c510603](https://github.com/chrismcdev/PeakRDL-check/commit/c510603dd290ae43c9f31674faa63dfa46e2fbd4))
* **diff:** semantic diff engine, severity policy, report formats, corpus runner ([18a799e](https://github.com/chrismcdev/PeakRDL-check/commit/18a799e7c9fef98b1b2aab6166778b705e85c85d))
* fixture generator, canonical model, SQLite index storage, initial CLI ([38f7576](https://github.com/chrismcdev/PeakRDL-check/commit/38f7576c97fe4303c032062983bd080ff34882b7))
* **packaging:** prepare PyPI distribution ([95a17f4](https://github.com/chrismcdev/PeakRDL-check/commit/95a17f4ea7e2c917c0981b074dd74d29658a2191))
* **plugin:** register 'peakrdl check' subcommand with the PeakRDL CLI ([aee264e](https://github.com/chrismcdev/PeakRDL-check/commit/aee264e80bdcf242c4e7111a61b8f1c3e5a402a5))
* **release:** add trusted publishing workflows ([745da2b](https://github.com/chrismcdev/PeakRDL-check/commit/745da2b390a67a426358898e334566d9e1157d76))
* **release:** automate PyPI releases ([989dc5b](https://github.com/chrismcdev/PeakRDL-check/commit/989dc5b7a94675ffdbcd85b3f2953eb83d7594da))
* **server:** local server and virtualized viewer, verified at 800k ([5dea986](https://github.com/chrismcdev/PeakRDL-check/commit/5dea98614aa44e55e9f3d1ab1327f5a683336d54))
* **tooling:** add repository automation, proof generators, and profiling ([7142119](https://github.com/chrismcdev/PeakRDL-check/commit/7142119eb8c8d4c39af6cf4fd7fc90a23e5239ed))


### Bug Fixes

* **ci:** install PeakRDL test dependency ([c34b64b](https://github.com/chrismcdev/PeakRDL-check/commit/c34b64b078b22157ff6ccc08ce49d19417aebd5c))
* **ci:** use Node 24 GitHub Actions ([6919730](https://github.com/chrismcdev/PeakRDL-check/commit/691973068926c4c0d0c74ccdbca9cbcb2ec53fe1))
* **logo:** add white background ([#3](https://github.com/chrismcdev/PeakRDL-check/issues/3)) ([2406820](https://github.com/chrismcdev/PeakRDL-check/commit/240682040618530fa0380e0ecdeb62aeb19718ef))
* **release:** prefix generated versions ([0aad571](https://github.com/chrismcdev/PeakRDL-check/commit/0aad571c2a48308fb900e978f92ef90d8ede97be))
* **repo:** finalize project naming and remove machine-specific paths ([8fc1f36](https://github.com/chrismcdev/PeakRDL-check/commit/8fc1f3689b632e2e542b5e2246ae0e75bd176da1))
* **scripts:** align benchmark runner name with project naming ([c7b6cdc](https://github.com/chrismcdev/PeakRDL-check/commit/c7b6cdc844821cb953585258bde2a3a4eb743db4))
* **test:** make CLI tests portable ([bebf52f](https://github.com/chrismcdev/PeakRDL-check/commit/bebf52f80015cee378b008f7ab3cccd9717badc4))


### Documentation

* add documentation set (13 docs, 10 ADRs, project meta); fix none-mode crash ([bb5e858](https://github.com/chrismcdev/PeakRDL-check/commit/bb5e8585a43a3d5178709b6c3bba0879e34c85f1))
* **community:** listing materials (table entry and show-and-tell draft) ([c5e027d](https://github.com/chrismcdev/PeakRDL-check/commit/c5e027db7090b9fa710e21ae71ffb19483c8aa4e))
* **contributing:** document Conventional Commits as the standard ([32f5d5f](https://github.com/chrismcdev/PeakRDL-check/commit/32f5d5fad3d18a5ec213320cdac02b2bc5dfd7cd))
* **proof:** full benchmark matrix, generated PROOF.md, README ([f122051](https://github.com/chrismcdev/PeakRDL-check/commit/f122051901231babea23fdaa3ce5184c8ebd4636))
* **readme:** add SystemRDL logo and streamline references ([#2](https://github.com/chrismcdev/PeakRDL-check/issues/2)) ([61cbe16](https://github.com/chrismcdev/PeakRDL-check/commit/61cbe165af364418709383e91621b6fb19204600))
* **readme:** reframe proof as differentiators, not requirements ([c77bc61](https://github.com/chrismcdev/PeakRDL-check/commit/c77bc61d14a2292953131228b48743040122d7a2))

## Changelog

Notable changes to PeakRDL-check are recorded here by the automated release process.
