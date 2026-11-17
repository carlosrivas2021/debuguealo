# Changelog

## [1.0.1](https://github.com/carlosrivas2021/debuguealo/compare/v1.0.0...v1.0.1) (2026-11-17)


### Documentation

* expression evaluation exists; only source editing is missing ([#97](https://github.com/carlosrivas2021/debuguealo/issues/97)) ([4a719f3](https://github.com/carlosrivas2021/debuguealo/commit/4a719f3cd7798b6b9d786d0b732dac106cfd86a9))

## [1.0.0](https://github.com/carlosrivas2021/debuguealo/compare/v0.7.0...v1.0.0) (2026-11-17)


### Features

* **code:** breakpoints list under the file tree ([6033605](https://github.com/carlosrivas2021/debuguealo/commit/603360519b0d7401388f87b1ad37c84a555029c0))
* **code:** collapsible breakpoints list, no breakpoints in the file tree ([b3784c3](https://github.com/carlosrivas2021/debuguealo/commit/b3784c31c5c3af6ca55a716df67f89d04d7c7842))
* **code:** Ctrl+F10 runs to the line under the source cursor ([a5620ed](https://github.com/carlosrivas2021/debuguealo/commit/a5620edb17b16dfa2d1488dd4d5c1505eb50dc12))
* **code:** debug console to evaluate expressions while paused ([e3d086c](https://github.com/carlosrivas2021/debuguealo/commit/e3d086c1498f93decbb88188d7ad9ef148befa8a))
* **code:** exception pauses select the project's own stack frame ([438bcec](https://github.com/carlosrivas2021/debuguealo/commit/438bcec39b84dcfc22684dc4fa4debe81e35a047))
* **code:** one line under the debug output, Program input or Evaluate ([08d93e9](https://github.com/carlosrivas2021/debuguealo/commit/08d93e9943c03b87687128cc96f9c16c0b07f72e))
* **code:** pause on exceptions, toggled per project with E ([bc30a84](https://github.com/carlosrivas2021/debuguealo/commit/bc30a84f170f134057fbaeab48d7f749093b3fed))
* **code:** switch breakpoints off without removing them ([a7ad222](https://github.com/carlosrivas2021/debuguealo/commit/a7ad2225bb38e4bf72dcb8364d4b2e02bc7edb68))
* **tui:** ? lists the area's shortcuts, grouped by task ([e6d0003](https://github.com/carlosrivas2021/debuguealo/commit/e6d0003a754de6604a2e700e7473131fc6cef75f))
* **tui:** colors follow the theme; debugealo theme by default, pick remembered ([2b432d6](https://github.com/carlosrivas2021/debuguealo/commit/2b432d65f095d076ce10d5c709f069e5634c597e))
* **tui:** Ctrl+P Keys opens the grouped shortcuts ([f5e2f04](https://github.com/carlosrivas2021/debuguealo/commit/f5e2f046dae81315838e754eab4f8f5d2a5de4d5))
* **tui:** text drawn from Python follows the theme too ([fdcdab4](https://github.com/carlosrivas2021/debuguealo/commit/fdcdab4345505512338a58876aa3da97e6ad1c55))


### Bug Fixes

* **code:** breakpoints title like PROFILES, visible focus, Enter enters the list ([7a3cd2e](https://github.com/carlosrivas2021/debuguealo/commit/7a3cd2ea182f68614b013840366e2c374f56916f))
* **code:** Run to cursor keeps hit counts, stops on conditional lines, survives edits ([56a9aaa](https://github.com/carlosrivas2021/debuguealo/commit/56a9aaa3b6476705718e929755966758c10fe9c6))
* **code:** show the exception mode in the Debug output title ([07d988c](https://github.com/carlosrivas2021/debuguealo/commit/07d988ce9a410a7be4ade5df17c09d06ed0ce848))
* **tui:** read launch profiles off the UI thread during refresh ([141ae81](https://github.com/carlosrivas2021/debuguealo/commit/141ae81d73f9d0b8ee2940c838f54576dc6a465e))


### Performance Improvements

* **code:** redraw the footer only when the offered keys change ([9f1606d](https://github.com/carlosrivas2021/debuguealo/commit/9f1606d29ed06eeaeb174402c2eac34e078dac9f))


### Miscellaneous Chores

* prepare the 1.0.0 release ([c1f36a9](https://github.com/carlosrivas2021/debuguealo/commit/c1f36a9ed122aa829ab380f7fe9ebd2847e14768))

## [0.7.0](https://github.com/carlosrivas2021/debuguealo/compare/v0.6.0...v0.7.0) (2026-11-16)


### Features

* **code:** change a paused variable from the Variables pane ([e2a5e89](https://github.com/carlosrivas2021/debuguealo/commit/e2a5e89cdabbc333f23ea09d96da3ab2f3fc6e1f))
* **code:** change debug variables while paused ([42179da](https://github.com/carlosrivas2021/debuguealo/commit/42179da997288110c6e0af60af8656ab13fbdf8c))
* **code:** Ctrl/Alt+arrows reach the debug panes ([44766a2](https://github.com/carlosrivas2021/debuguealo/commit/44766a22bb3f3798d5d95bef4a49d4049f03747d))
* **code:** expand nested variables ([9a681eb](https://github.com/carlosrivas2021/debuguealo/commit/9a681eb9c318cc50a0bced1c4c1d339e0c2a8448))
* **code:** expand nested variables and change their fields ([8948b9c](https://github.com/carlosrivas2021/debuguealo/commit/8948b9cfab8bdcdf3e2853b51ea7ca219010bc6e))
* **code:** name the profile in the Debug output title, not on every line ([9b61d1b](https://github.com/carlosrivas2021/debuguealo/commit/9b61d1b08bda9d4ae019e01ad78fd56531e1ea9e))
* **code:** Python debug output shows the program's terminal ([eec73f7](https://github.com/carlosrivas2021/debuguealo/commit/eec73f776d13c56ffd5dd8e0f4aef9afcdac124a))
* **code:** Python debug output shows the program's terminal, getpass prompt included ([8157f9f](https://github.com/carlosrivas2021/debuguealo/commit/8157f9ff2efef79110c240949ecc2ea25f2c21b9))
* **code:** Right and Left open and close folders in the file tree ([a474ad1](https://github.com/carlosrivas2021/debuguealo/commit/a474ad14bd05a9a1f2dcfad88d936248c1a2806d))
* **code:** show and copy a variable's whole value ([d00eec4](https://github.com/carlosrivas2021/debuguealo/commit/d00eec4560e48efbf1f8c0110f288efccae2d964))
* **code:** show and copy a variable's whole value ([3d5fdff](https://github.com/carlosrivas2021/debuguealo/commit/3d5fdfff38a09a5070daf5d6054afababed5a526))
* **code:** watches with fields expand like variables ([0320455](https://github.com/carlosrivas2021/debuguealo/commit/032045510bab81c0701b9786e7d8e76883ee40de))
* **code:** watches with fields expand like variables ([147065d](https://github.com/carlosrivas2021/debuguealo/commit/147065d9b4277e796fe69ee5c73f3248f643a9bd))
* **debugger:** set a paused variable to a value expression ([946bb87](https://github.com/carlosrivas2021/debuguealo/commit/946bb87ac7c5ac2940df7952e1defadf331f8daa))


### Bug Fixes

* **code:** focus returns to the profiles when the debug panel closes ([6663e90](https://github.com/carlosrivas2021/debuguealo/commit/6663e90cbb4f0b8b30a5484e5bf2533aae3838a6))

## [0.6.0](https://github.com/carlosrivas2021/debuguealo/compare/v0.5.2...v0.6.0) (2026-11-15)


### Features

* **code:** P goes to the program's input, Esc leaves it ([5759bda](https://github.com/carlosrivas2021/debuguealo/commit/5759bdae4a1bca78020a11f0b470ed8de9bfd126))
* **code:** P goes to the running program's input ([bb563fe](https://github.com/carlosrivas2021/debuguealo/commit/bb563fe362e497f3d979cd7abb09b958b4deec9d))
* **tui:** filter the Containers and Code lists with / ([b544a3d](https://github.com/carlosrivas2021/debuguealo/commit/b544a3dcf468f7e03d732db180b9ee2943a74730))
* **tui:** filter the Containers and Code lists with / ([77e6ce9](https://github.com/carlosrivas2021/debuguealo/commit/77e6ce98beea1f9a73dd94d706178484d6545bcb))


### Bug Fixes

* **code:** drop Node output lines made only of cursor moves ([57307b8](https://github.com/carlosrivas2021/debuguealo/commit/57307b88a4eeb84c4021e67e1c7a4354579607db))
* **code:** Esc leaves the Program input field ([24ca5d7](https://github.com/carlosrivas2021/debuguealo/commit/24ca5d7d5829edeedcb5f7b5f1f2d8b40a756cab))
* **tui:** filter no longer crashes on a hidden profile row; Esc clears it from the list ([42e3004](https://github.com/carlosrivas2021/debuguealo/commit/42e3004ae416683794f107f7cecc09918111aa1c))


### Performance Improvements

* **code:** moving between profiles no longer touches the disk per file ([378d180](https://github.com/carlosrivas2021/debuguealo/commit/378d180ba17cb19220e46feabfeebfe3db1dc17f))
* **code:** moving between profiles no longer touches the disk per file ([4cc3bf6](https://github.com/carlosrivas2021/debuguealo/commit/4cc3bf6e9d00efb37edfc482e13bc71fddd8ce05))

## [0.5.2](https://github.com/carlosrivas2021/debuguealo/compare/v0.5.1...v0.5.2) (2026-11-14)


### Bug Fixes

* **code:** clean debug output on Windows (empty lines, hidden prompts) ([9fb7203](https://github.com/carlosrivas2021/debuguealo/commit/9fb7203f14d6f45a896a3015bb0ed7d92b35f21c))
* **code:** show Node prompts that wait without a newline ([ddd8e3f](https://github.com/carlosrivas2021/debuguealo/commit/ddd8e3f6748da0f5b7b83a3da44d520caeb423e7))
* **code:** stop empty debug output lines after each print ([815d6d2](https://github.com/carlosrivas2021/debuguealo/commit/815d6d2a1c1e7aa490f9d1613d89de55fa739f5a))

## [0.5.1](https://github.com/carlosrivas2021/debuguealo/compare/v0.5.0...v0.5.1) (2026-11-14)


### Bug Fixes

* **code:** end program input on Windows with Ctrl+Z and Enter ([76c4f29](https://github.com/carlosrivas2021/debuguealo/commit/76c4f29f763d14ed4cc10eede6872e5023f20842))
* **code:** hide typed program input when the echo mode is unknown ([b97b2fe](https://github.com/carlosrivas2021/debuguealo/commit/b97b2feb016f6a7328ef25f3439fdab5f43cd326))
* **code:** Windows program input ends with Ctrl+D and keeps passwords hidden ([05ab109](https://github.com/carlosrivas2021/debuguealo/commit/05ab1096c6d789e8b74c1503c2395d0494529d51))
* **deps:** allow pywinpty 3 so Windows installs on Python 3.14 ([b8884a0](https://github.com/carlosrivas2021/debuguealo/commit/b8884a0567b324e75999721be5bd49b399f17576))
* **deps:** allow pywinpty 3 so Windows installs on Python 3.14 ([38cc114](https://github.com/carlosrivas2021/debuguealo/commit/38cc114e45735bc1b58f3d5a3976e2c8ac4221c6))

## [0.5.0](https://github.com/carlosrivas2021/debuguealo/compare/v0.4.0...v0.5.0) (2026-11-14)


### Features

* **code:** debug TypeScript with Node's native type stripping ([e9b7cc1](https://github.com/carlosrivas2021/debuguealo/commit/e9b7cc1639c9c0829f82b20ec55caa00f9d9d579))
* **code:** debug TypeScript with Node's native type stripping ([a85dbe9](https://github.com/carlosrivas2021/debuguealo/commit/a85dbe9aee2ab0f86f1f86f2bef0938fd168b3a3))
* **code:** map compiled TypeScript through source maps in Node debugging ([fd93797](https://github.com/carlosrivas2021/debuguealo/commit/fd93797ed8cfdfdd941f8de035643c623c833434))
* **code:** map compiled TypeScript through source maps in Node debugging ([ce5ecb5](https://github.com/carlosrivas2021/debuguealo/commit/ce5ecb5fac29f3ec83e3dadbdc0934a717e5c24b))
* **code:** send program input while debugging ([0ec8212](https://github.com/carlosrivas2021/debuguealo/commit/0ec821253c6e2210f4f2a3fd0b7166ee84c0dede))
* **code:** send program input while debugging ([8a4b0b3](https://github.com/carlosrivas2021/debuguealo/commit/8a4b0b352b03efb003a459e2d7aae395f86f7ebc))
* **code:** stop breakpoints on a hit count ([9ea3d85](https://github.com/carlosrivas2021/debuguealo/commit/9ea3d856efe72971fc7d1116e491ec26fddbc96c))
* **code:** stop breakpoints on a hit count ([cb30df3](https://github.com/carlosrivas2021/debuguealo/commit/cb30df30c7c7c0b70183b2f91a514cb61682248c))
* **tui:** show container health, restarts, exit code, mounts and env names ([625edc2](https://github.com/carlosrivas2021/debuguealo/commit/625edc29e33b0d42df2fc7c395d5c019cb18d23a))
* **tui:** show container health, restarts, exit code, mounts and env names ([482b8a7](https://github.com/carlosrivas2021/debuguealo/commit/482b8a7d7dae11a0c3ee52eceb1cc13161e049f3))
* **tui:** show the log search match count and jump back with Shift+N ([9941dc4](https://github.com/carlosrivas2021/debuguealo/commit/9941dc41e899b5122367dcee20e4e168dc0a30f5))
* **tui:** show the log search match count and jump back with Shift+N ([8b772a5](https://github.com/carlosrivas2021/debuguealo/commit/8b772a53dfb7b85cda14f0d33a03ae75a95eaeb5))


### Bug Fixes

* **code:** bound the source map index walk and skip Python environments ([06b3bdd](https://github.com/carlosrivas2021/debuguealo/commit/06b3bddfe70ed2a9c99c07826d03fa23fb6f563b))
* **storage:** accept only ASCII digits in breakpoint hit counts ([bb1f7b4](https://github.com/carlosrivas2021/debuguealo/commit/bb1f7b457c05e7c8c2c10ac5ff48cfbfe657f9b0))
* **tui:** skip editor title refresh while its panes are not all mounted ([b60bb71](https://github.com/carlosrivas2021/debuguealo/commit/b60bb7180fd959fe46bf42cad3560548ede2887f))

## [0.4.0](https://github.com/carlosrivas2021/debuguealo/compare/v0.3.0...v0.4.0) (2026-11-14)


### Features

* **code:** attach to an existing Node Inspector ([936f2b2](https://github.com/carlosrivas2021/debuguealo/commit/936f2b2d0bd1828379e30c28fd24ac23665b3b23))
* **code:** attach to an existing Node Inspector with nodeAttach ([dcd1600](https://github.com/carlosrivas2021/debuguealo/commit/dcd16009e8652eca061d2d12d051e04485270646))
* **code:** list local Git branches and switch between them ([40b44fb](https://github.com/carlosrivas2021/debuguealo/commit/40b44fbbac5f18f220dd044585c008ede7cb82ea))
* **code:** list local Git branches and switch between them ([4f6bbbc](https://github.com/carlosrivas2021/debuguealo/commit/4f6bbbc9a76e179d09c04828d77b5e53529953a8))
* **code:** switch Git branch from the Code bar ([89b6af2](https://github.com/carlosrivas2021/debuguealo/commit/89b6af26fee5e14be19ba125f6d1dda50863a9c5))
* **code:** switch Git branch from the Code bar ([70d382f](https://github.com/carlosrivas2021/debuguealo/commit/70d382f0874e254f03dc85267f2f5e8e0be6ddd9))
* **storage:** load and save editor text atomically ([c574588](https://github.com/carlosrivas2021/debuguealo/commit/c57458875307133cc779e2e770a82f6cc87ddbc2))
* **storage:** load and save editor text atomically ([d72c34e](https://github.com/carlosrivas2021/debuguealo/commit/d72c34e0f6a137c6c4f0b83523c6f08037e77a6b))
* **tui:** add an in-app editor screen for one or two files ([8aa0c8a](https://github.com/carlosrivas2021/debuguealo/commit/8aa0c8a863e2e5234fef9ee2ca0598075e742714))
* **tui:** add an in-app editor screen for one or two files ([03227bc](https://github.com/carlosrivas2021/debuguealo/commit/03227bca9c571665ba60448bea11903ab28c5788))
* **tui:** copy container log rows by dragging and wrap long lines ([20291fa](https://github.com/carlosrivas2021/debuguealo/commit/20291faa8be9e728ca0c165133ebd45b50494af4))
* **tui:** copy container log rows by dragging and wrap long lines ([563769e](https://github.com/carlosrivas2021/debuguealo/commit/563769e2ea4396db1c3ae2e9194b20ec72bedb89))
* **tui:** edit launch.json in the built-in editor with Ctrl+O ([e6080f4](https://github.com/carlosrivas2021/debuguealo/commit/e6080f463ab53401a6ac815b9ffacaaf5d42164c))
* **tui:** edit launch.json in the built-in editor with Ctrl+O ([606a6af](https://github.com/carlosrivas2021/debuguealo/commit/606a6af4de6eeb758daaa3b9bd9ac6ccf4215779))
* **tui:** edit the AWS config and credentials side by side with Shift+A ([ace2bef](https://github.com/carlosrivas2021/debuguealo/commit/ace2bef9fe0e1731e0f1eeaa9470d23771f05cab))
* **tui:** edit the AWS config and credentials side by side with Shift+A ([d65bd3c](https://github.com/carlosrivas2021/debuguealo/commit/d65bd3c03b33efcfa5dcfb30d557817c412f6023))
* **tui:** move between panes with Alt+Left/Right ([e8243cf](https://github.com/carlosrivas2021/debuguealo/commit/e8243cf95ca666d0fe9b2e59a82f45829bf671d8))
* **tui:** move between panes with Alt+Left/Right ([0058ee1](https://github.com/carlosrivas2021/debuguealo/commit/0058ee1f8b62e22ecfa173410830acfa272092a6))
* **tui:** open the AWS files with Shift+A from Code too ([4a39e1b](https://github.com/carlosrivas2021/debuguealo/commit/4a39e1b751a77d947263597296d5c5707174362b))


### Bug Fixes

* **code:** harden Node attach discovery and disconnect ([4ccffef](https://github.com/carlosrivas2021/debuguealo/commit/4ccffef52d3799acc5b736d0f5be4f3d65156783))
* **code:** report malformed Node Inspector replies as attach errors ([6b5fc6d](https://github.com/carlosrivas2021/debuguealo/commit/6b5fc6dc184f4cf32b14dcac055cd60eb32c8520))
* **storage:** detect same-size outside writes before saving ([e30598f](https://github.com/carlosrivas2021/debuguealo/commit/e30598fc9073102b6f90539a8efd2a7c56bb7218))
* **tui:** keep mouse selection smooth and copy from the source viewer ([2869cad](https://github.com/carlosrivas2021/debuguealo/commit/2869cad23d2deded6cec2e54c8ffb1871e83b1ef))
* **tui:** keep mouse selection smooth and copy from the source viewer ([882de2f](https://github.com/carlosrivas2021/debuguealo/commit/882de2f50b06feea8dcabfdc1d0c6b165cb7234c))
* **tui:** keep the previous message for an oversized launch.json ([4d31512](https://github.com/carlosrivas2021/debuguealo/commit/4d315120cc36b02ecbe2b6bbfa4103f6896ff7f8))

## [0.3.0](https://github.com/carlosrivas2021/debuguealo/compare/v0.2.0...v0.3.0) (2026-11-11)


### Features

* **tui:** announce newer releases on the dashboard ([e53a78c](https://github.com/carlosrivas2021/debuguealo/commit/e53a78c48a99c2ddcae180ea2d090a6a43a00520))
* **tui:** announce newer releases on the dashboard ([533262f](https://github.com/carlosrivas2021/debuguealo/commit/533262fe1d701e9f005026df900520da431037bd))

## [0.2.0](https://github.com/carlosrivas2021/debuguealo/compare/v0.1.0...v0.2.0) (2026-11-11)


### Features

* add Code project workspaces with multi-language debugging ([dd36af7](https://github.com/carlosrivas2021/debuguealo/commit/dd36af7fc45f9871ec2ae84e21174451d6d7547c))
* **cli:** check Delve and debugpy in doctor ([1c1e0f5](https://github.com/carlosrivas2021/debuguealo/commit/1c1e0f5d3f0b0ab4c83c4957bdb9a8ad99197fb8))
* **cli:** check Delve and debugpy in doctor ([ebc675c](https://github.com/carlosrivas2021/debuguealo/commit/ebc675c29b17fe7787c6a2983a3b4a2d9b046451))
* **cli:** diagnose local Docker through isolated workers ([1201921](https://github.com/carlosrivas2021/debuguealo/commit/12019219fd0a783cf09a1e83e4b1a9e8545852fe))
* **cli:** integrate owned Docker streams and container commands ([7621cd6](https://github.com/carlosrivas2021/debuguealo/commit/7621cd6824d2eab81ae65a80a83cd29444edc01e))
* **code:** add env and envFile to Code profiles ([01bf47a](https://github.com/carlosrivas2021/debuguealo/commit/01bf47a0883168decd1858381b6e33c9800cf1be))
* **code:** add env and envFile to Code profiles ([c070db5](https://github.com/carlosrivas2021/debuguealo/commit/c070db52d3ad6bd7b7027d16d234eb2dd976437a))
* **code:** browse source and mark pending line breakpoints ([ab6b2ba](https://github.com/carlosrivas2021/debuguealo/commit/ab6b2ba9deaabdb605e7f6e5d3a95bbdcc281290))
* **code:** connect Go attach profiles without owning containers ([5b6c31e](https://github.com/carlosrivas2021/debuguealo/commit/5b6c31e930ca0b1f57b58ffaa1e87a6d30547273))
* **code:** continue a paused debug session with F5 ([aa066be](https://github.com/carlosrivas2021/debuguealo/commit/aa066be17eb6ecd8656f12f3975410fbdf3a414b))
* **code:** debug Node scripts and explicit npm targets ([92deb74](https://github.com/carlosrivas2021/debuguealo/commit/92deb74464d048804470d3b0b1fc814d8c1c7977))
* **code:** integrate Go debugging with explicit unavailable exit status ([0c852bc](https://github.com/carlosrivas2021/debuguealo/commit/0c852bcfad954ac8de2de0bf1b19e68e3bacbdea))
* **code:** integrate Python debugging and inspection controls ([d28fa7c](https://github.com/carlosrivas2021/debuguealo/commit/d28fa7c3059a928ac965b37a86f278865eec2915))
* **code:** mark running and debugging profiles with an icon ([50cc571](https://github.com/carlosrivas2021/debuguealo/commit/50cc5718273eb628d02e0fcae3b33d8aeab22593))
* **code:** persist requested breakpoints across restarts ([345e0c0](https://github.com/carlosrivas2021/debuguealo/commit/345e0c06a88078c4316034b710e6379e0a0508f0))
* **code:** reload profiles with R ([a16ceab](https://github.com/carlosrivas2021/debuguealo/commit/a16ceab1c19c1ef12cc1b4eae2d30ba645386552))
* **code:** reload with R; fix(terminal): Ctrl+C copies a selection ([0dded45](https://github.com/carlosrivas2021/debuguealo/commit/0dded45222ebb64c9f021414cf15aa6659df9c3a))
* **code:** restart a running profile with R ([bd25758](https://github.com/carlosrivas2021/debuguealo/commit/bd2575889f00068974b8b23eb82b854b4f96a1f4))
* **code:** restart a running profile with R ([9ea6cd7](https://github.com/carlosrivas2021/debuguealo/commit/9ea6cd786dfc964747c57e5d35e33c1cda91154d))
* **code:** run distinct profiles concurrently ([2fef308](https://github.com/carlosrivas2021/debuguealo/commit/2fef308ccda66879dcb4e33806065745e7bfd20f))
* **code:** run managed local processes with tree cleanup ([29db5a1](https://github.com/carlosrivas2021/debuguealo/commit/29db5a1db28fc3541f9827cdff640ebf0f364d52))
* **code:** show clickable red breakpoint markers in source gutter ([aa28334](https://github.com/carlosrivas2021/debuguealo/commit/aa283344bbc3b060af38ffca1c36a086f214aae1))
* **code:** show the Git branch and a run/debug icon for profiles ([16e76c9](https://github.com/carlosrivas2021/debuguealo/commit/16e76c96562c20bd10805b37463befbba2028688))
* **code:** show the selected profile's Git branch ([1f173b3](https://github.com/carlosrivas2021/debuguealo/commit/1f173b34e552d526145f266167f041a1e2a760c6))
* **code:** toggle breakpoints with F9 ([7d63db6](https://github.com/carlosrivas2021/debuguealo/commit/7d63db68b94971fdeb0d4895cf506ede4e152333))
* **code:** validate centrally registered project profiles ([c07f748](https://github.com/carlosrivas2021/debuguealo/commit/c07f748dad82b7157e74b673eb4325d2c8ad0519))
* **compose:** add confirmed local lifecycle operations ([3fd5e5f](https://github.com/carlosrivas2021/debuguealo/commit/3fd5e5fbf48b1f8f5b88f8de346ca3d97308b06a))
* **compose:** add pure service override model ([2122aa1](https://github.com/carlosrivas2021/debuguealo/commit/2122aa1a3c2e855d9873d3ca95421c503ebda53f))
* **compose:** browse files and confirm project startup ([5fe668d](https://github.com/carlosrivas2021/debuguealo/commit/5fe668dc4f91bb4dec0d1a5965adce383a2d893d))
* **core:** add installable local settings and bounded lifecycle ([39ea545](https://github.com/carlosrivas2021/debuguealo/commit/39ea545ec2a023f6c8bf35c8309e62bd4dfdb2e7))
* **credentials:** refresh AWS credentials for launch profiles ([91a2b77](https://github.com/carlosrivas2021/debuguealo/commit/91a2b7762cb0cb8ac565d24b75e8e4871834b579))
* **debug:** add bounded loopback Inspector transport ([1679506](https://github.com/carlosrivas2021/debuguealo/commit/16795063d049e7e67c320c41ec9c9c2e1eb3bb6f))
* **debug:** add Go Delve sessions with explicit optional exit status ([9b3d301](https://github.com/carlosrivas2021/debuguealo/commit/9b3d301e5b524f90cbe0cc484cd4ec015b74961d))
* **debug:** add owned Python debugging sessions ([965624f](https://github.com/carlosrivas2021/debuguealo/commit/965624f3e929893c6dfa37290bf2b01d45a1c673))
* **debug:** attach to existing Python debugpy targets ([f355fcc](https://github.com/carlosrivas2021/debuguealo/commit/f355fccb9f39049208f0e690e693a11066edaada))
* **debug:** attach to existing Python debugpy targets ([555db77](https://github.com/carlosrivas2021/debuguealo/commit/555db771a766049caaa17bfa5bc373300e377b29))
* **debug:** bundle debugpy for Python debugging ([7508a40](https://github.com/carlosrivas2021/debuguealo/commit/7508a40db12a00672ba9b069fc60ac6a17885df8))
* **debug:** evaluate watch expressions in a paused frame ([637e147](https://github.com/carlosrivas2021/debuguealo/commit/637e147bc40eddb22a6c4b274c19db163bd6d72f))
* **debug:** recover lost Go attach connections explicitly ([2211974](https://github.com/carlosrivas2021/debuguealo/commit/2211974c68e29c04519e1beb06b4c08d29eecb79))
* **debug:** send breakpoint conditions and log messages to adapters ([78a9a10](https://github.com/carlosrivas2021/debuguealo/commit/78a9a10d1b6040f6909cb18c57b1ab3950f6f2cd))
* **debug:** support non-owning Go remote attach sessions ([1369b27](https://github.com/carlosrivas2021/debuguealo/commit/1369b27760cd639e3e1717a7b95c2c2284ab9a04))
* **docker:** expose read-only inventory and log services ([478273f](https://github.com/carlosrivas2021/debuguealo/commit/478273f4e5fb17b662e9f60ad236770b9621c3bf))
* **docker:** read container stats samples through the inventory worker ([8709c64](https://github.com/carlosrivas2021/debuguealo/commit/8709c64212923e4dd5a738ed6709bb9e2bf4efb7))
* **docker:** read container stats samples through the inventory worker ([79ff008](https://github.com/carlosrivas2021/debuguealo/commit/79ff008f3a236bd37fb7e798d0cfdde7c57b7200))
* **examples:** add FastAPI debug example for Python attach ([dba3d04](https://github.com/carlosrivas2021/debuguealo/commit/dba3d0464d63a006c3cc780722bdaa67d1edaef6))
* **examples:** add three connected Compose projects ([3309528](https://github.com/carlosrivas2021/debuguealo/commit/3309528876cf0da269dea9778671e4a47e3bb695))
* integrate compose overrides and dashboard terminal ([ab9c9d1](https://github.com/carlosrivas2021/debuguealo/commit/ab9c9d172b74a4c38067957a53e77d6ddfef5dd6))
* land the MVP close-out stack on main ([e1a277f](https://github.com/carlosrivas2021/debuguealo/commit/e1a277f1beb1d3875221d0a38b6ce6e6e64c4a8f))
* **launch:** limit compose profiles to selected services ([c5bc3a2](https://github.com/carlosrivas2021/debuguealo/commit/c5bc3a29476435135255f1eb42180c46a9461744))
* **launch:** use central profiles with explicit project roots ([2520eab](https://github.com/carlosrivas2021/debuguealo/commit/2520eab4cfe872268533dc111a1ceae8838e3b87))
* **logs:** decode bounded channels and replay cursors ([5acfa37](https://github.com/carlosrivas2021/debuguealo/commit/5acfa37ed56a79c865827811d4deb5b71050db1e))
* persist and evaluate watch expressions (backend) ([d08b4c8](https://github.com/carlosrivas2021/debuguealo/commit/d08b4c827bf2adbb12bfd8f29956968cb7a42dee))
* rename product to debugealo with legacy compatibility ([96c5d26](https://github.com/carlosrivas2021/debuguealo/commit/96c5d263da963833d66e2d7ae7e4d4efe3bd8399))
* **storage:** persist breakpoint conditions and log messages ([7a89c8d](https://github.com/carlosrivas2021/debuguealo/commit/7a89c8deabecd0959c2755fc973a41b2549c4e3d))
* **storage:** persist breakpoint conditions and log messages ([3a034ee](https://github.com/carlosrivas2021/debuguealo/commit/3a034eeebee29e00850d1f581377b40e0f1b9d1a))
* **storage:** persist watch expressions per project ([f22c3a9](https://github.com/carlosrivas2021/debuguealo/commit/f22c3a9238b7d7ed0724a3d632a7602bd9c9cef6))
* **terminal:** add isolated embedded terminal backend ([b4e9d81](https://github.com/carlosrivas2021/debuguealo/commit/b4e9d8110302735918e78b10f1c77c61f9e34afa))
* **tui:** add a Watch section to the debug panel ([904d88e](https://github.com/carlosrivas2021/debuguealo/commit/904d88e4101694b169466fb7049277c5d2b46b38))
* **tui:** add a Watch section to the debug panel ([afb4f40](https://github.com/carlosrivas2021/debuguealo/commit/afb4f406a405f38a7b1fa425c17337e0bbd97cab))
* **tui:** add central Code project registration area ([7009e0a](https://github.com/carlosrivas2021/debuguealo/commit/7009e0ab9fcdaca75ca71b8b69fb8462486b1c6e))
* **tui:** add container dashboard and confirmed Compose controls ([326d4b0](https://github.com/carlosrivas2021/debuguealo/commit/326d4b04ad4adb341a66cb3998017b4a6ff66bb8))
* **tui:** add dynamic launch profiles and confirmed stop controls ([8bcb5bf](https://github.com/carlosrivas2021/debuguealo/commit/8bcb5bfc6542ac4e29390404f0ade9329499f071))
* **tui:** compact breakpoint panel, inline condition hints and Code pane navigation ([4dade84](https://github.com/carlosrivas2021/debuguealo/commit/4dade843bf228e2bb9470b3faf0a537adce7b9fe))
* **tui:** copy text on select with a short notice ([14d6dbf](https://github.com/carlosrivas2021/debuguealo/commit/14d6dbf2216815563dab3364eda2d7650d4e7e90))
* **tui:** copy text on select with a short notice ([31b505b](https://github.com/carlosrivas2021/debuguealo/commit/31b505b737ca3bdef426ad0a6ed8b6b1c9290ae6))
* **tui:** Ctrl+arrows in Containers and a more readable debug panel ([1041e9e](https://github.com/carlosrivas2021/debuguealo/commit/1041e9e54fe6f81c4840de2b1d40e9cbeb3838b9))
* **tui:** drop the profile folder and command block from Code ([daa2090](https://github.com/carlosrivas2021/debuguealo/commit/daa20902ff1839e1f83b67e082b8a00bb944ea42))
* **tui:** drop the profile folder and command block from Code ([42450c2](https://github.com/carlosrivas2021/debuguealo/commit/42450c2eeb1ae8b806c2030fca428297d47e7100))
* **tui:** edit breakpoint conditions and logpoints with Shift+F9 ([b6447e6](https://github.com/carlosrivas2021/debuguealo/commit/b6447e634262b63f78859ed0742eb90b378cbc04))
* **tui:** edit breakpoint conditions and logpoints with Shift+F9 ([252bb55](https://github.com/carlosrivas2021/debuguealo/commit/252bb55e09ef6ad1c0064b904565ef24e8d9d47d))
* **tui:** group Compose services and add contextual actions ([a81dc86](https://github.com/carlosrivas2021/debuguealo/commit/a81dc86132d74248d5b88327d66a840eb3e14819))
* **tui:** group containers under saved launch profiles ([a4979a5](https://github.com/carlosrivas2021/debuguealo/commit/a4979a514a6f018d0777a1b7a6dea44fb609223e))
* **tui:** IDE-style layout for the Code area ([e6f4e71](https://github.com/carlosrivas2021/debuguealo/commit/e6f4e71d9504821207de39539123a8077e3dbe0c))
* **tui:** IDE-style layout for the Code area ([a3afc7f](https://github.com/carlosrivas2021/debuguealo/commit/a3afc7fa710f461bb54da169e40c24eba1198b3d))
* **tui:** make it clear when a Code run is running or stopped ([1c010d2](https://github.com/carlosrivas2021/debuguealo/commit/1c010d2be01d74a4a2964628ac5d360fc2e815dd))
* **tui:** make it clear when a Code run is running or stopped ([d1366b2](https://github.com/carlosrivas2021/debuguealo/commit/d1366b2c03d391795e055d4198c3cb7eaceb9378))
* **tui:** make the breakpoint dialog a compact panel that keeps the line visible ([0702c14](https://github.com/carlosrivas2021/debuguealo/commit/0702c147fe5656f6a62b10e5b157257419c2d57d))
* **tui:** make the debug panel easier to read ([b24939f](https://github.com/carlosrivas2021/debuguealo/commit/b24939f3a039e77bec1e46b72ba8ed63c11b78b2))
* **tui:** move between Code panes with Ctrl+arrows and show breakpoint options ([ddfd6fb](https://github.com/carlosrivas2021/debuguealo/commit/ddfd6fb70a17f64c7c73fe5ecd594e9090733a84))
* **tui:** move between the list and the logs with Ctrl+arrows in Containers ([eab48ec](https://github.com/carlosrivas2021/debuguealo/commit/eab48ec3a009adede5542dc3dba52447207144e5))
* **tui:** open the breakpoint editor where the read-only panel is ([762dbd2](https://github.com/carlosrivas2021/debuguealo/commit/762dbd2c2eaf32910b424bf2f36c190ae5824b27))
* **tui:** persist compose actions and isolate current-run logs ([b0f3b13](https://github.com/carlosrivas2021/debuguealo/commit/b0f3b13c07c610c617d72ac8fde890758210a4d2))
* **tui:** redesign the containers view, output card and host terminal ([f2f3048](https://github.com/carlosrivas2021/debuguealo/commit/f2f3048277e4f561c555a2dff5b4b757c2061854))
* **tui:** redesign the containers view, output card and host terminal ([9fd8986](https://github.com/carlosrivas2021/debuguealo/commit/9fd89865681bfb79decff5fb6215e33a95afbdb1))
* **tui:** resizable profiles pane with the count in its title ([7f27f0b](https://github.com/carlosrivas2021/debuguealo/commit/7f27f0ba2723866fd8192e8f53aa88f6c7f32cdf))
* **tui:** resizable profiles pane with the count in its title ([d43cc6c](https://github.com/carlosrivas2021/debuguealo/commit/d43cc6c186eee4feb71580ee370b5a554d27e69e))
* **tui:** run code profiles with F5 and an interactive console ([4d7c735](https://github.com/carlosrivas2021/debuguealo/commit/4d7c7353331229bebcf919b370caa89550246b41))
* **tui:** run Compose for several projects at once with per-project output ([4e76e13](https://github.com/carlosrivas2021/debuguealo/commit/4e76e132a02420c86658f2f0d35468cd298cb747))
* **tui:** run Compose for several projects at once with per-project output ([332abc2](https://github.com/carlosrivas2021/debuguealo/commit/332abc2735ef2b54674876089aa26acf3d34b3f7))
* **tui:** separate stopped containers behind show-all toggle ([0fec15c](https://github.com/carlosrivas2021/debuguealo/commit/0fec15ca002a391c2d3604e50976a18558ea8373))
* **tui:** show breakpoint conditions as dim hints after the code ([f9df088](https://github.com/carlosrivas2021/debuguealo/commit/f9df0885d5835f749fc955a081ca938eaf0537d2))
* **tui:** show container details by default and open logs on demand ([8e60f12](https://github.com/carlosrivas2021/debuguealo/commit/8e60f120292a637044411f196fae127bed7d6dd4))
* **tui:** show live CPU and memory in the container details card ([cf05f65](https://github.com/carlosrivas2021/debuguealo/commit/cf05f655b1de46f36162b07cd16b78edc6c8ddd1))
* **tui:** show live CPU and memory in the container details card ([304d516](https://github.com/carlosrivas2021/debuguealo/commit/304d516e700e3cc882a387f402f93a6a8a3ee207))
* **tui:** switch between Containers and Code with Ctrl+T ([43383ae](https://github.com/carlosrivas2021/debuguealo/commit/43383aef6e69345af9b7b9a81d7098d565a65513))
* **tui:** toggle the Code output with O instead of Ctrl+J ([06f091a](https://github.com/carlosrivas2021/debuguealo/commit/06f091a182f2989a751eb9081a617609df7d8633))
* **tui:** toggle the Code output with O instead of Ctrl+J ([3299c7d](https://github.com/carlosrivas2021/debuguealo/commit/3299c7de105eea6c69b8b991d7b6bdd9b261e40c))


### Bug Fixes

* breakpoint follow-ups for Node logpoint braces and tree labels ([d88c0c0](https://github.com/carlosrivas2021/debuguealo/commit/d88c0c0835a102e55dd2365f9056d7f3913b5066))
* **code:** apply the profile PATH in Debug and follow dotenv conventions ([cb315bd](https://github.com/carlosrivas2021/debuguealo/commit/cb315bd4eea2640b901cc61219352e290a72d389))
* **code:** keep one session per profile during attach recovery ([22cb31f](https://github.com/carlosrivas2021/debuguealo/commit/22cb31f48ebb81376d9fc315964dbdb98a44cac2))
* **compose:** apply overrides as an appended file and find user CLI plugins ([985d663](https://github.com/carlosrivas2021/debuguealo/commit/985d663b6652ab377c063ee9d2c2c4e0cf9919bd))
* **compose:** contain plugin descendants during cancellation ([e6590c1](https://github.com/carlosrivas2021/debuguealo/commit/e6590c1bac9089a8fbaf52742afc9405edce201f))
* **compose:** forward SSH_AUTH_SOCK so builds can use the SSH agent ([cb8c37c](https://github.com/carlosrivas2021/debuguealo/commit/cb8c37c09ba7cb28dfc0f0aa9ede5cbdf18988d1))
* **compose:** make the Compose timeout configurable, default one hour ([7bd38cf](https://github.com/carlosrivas2021/debuguealo/commit/7bd38cf060b6821ea99dbde59fe543da5c69e7ed))
* **compose:** retain Windows system plugin search paths ([8b5c807](https://github.com/carlosrivas2021/debuguealo/commit/8b5c807da2d61caa2cee54c0b725a9178f28fa52))
* **core:** preserve asynchronous cleanup under repeated cancellation ([9ac9c6a](https://github.com/carlosrivas2021/debuguealo/commit/9ac9c6a13eaa858938cd7868dba599d9f6cd2106))
* **debug:** clear Go session breakpoints and resume on disconnect ([9ed9e7e](https://github.com/carlosrivas2021/debuguealo/commit/9ed9e7e86659e8d258d3aba0dc32ea230e91c099))
* **debug:** do not count the Go build against the startup timeout ([02af628](https://github.com/carlosrivas2021/debuguealo/commit/02af628ea571488109bf0993a623f27ea1cd06fd))
* **debug:** do not count the Go build against the startup timeout ([3f60ca9](https://github.com/carlosrivas2021/debuguealo/commit/3f60ca9f708a2bc298942551ab15d7d3740f5dac))
* **debug:** keep Node logpoints working with braces in messages ([49e16fa](https://github.com/carlosrivas2021/debuguealo/commit/49e16faa8c77eabd9178dcfd80429da21fa3c015))
* **debug:** keep paused controls and view state stable ([658515c](https://github.com/carlosrivas2021/debuguealo/commit/658515c95fd5d3564948b44c779b203a62ecc7bb))
* **examples:** isolate service image export tags ([8789e48](https://github.com/carlosrivas2021/debuguealo/commit/8789e488439dd1c47895a237137987c487e7596d))
* F5 in real terminals and bundled debugpy for Python debugging ([ac2b543](https://github.com/carlosrivas2021/debuguealo/commit/ac2b543ef9179d972a6400a34681371b62b97b04))
* **go:** enable plain uv debugging without VCS metadata ([6d18e8c](https://github.com/carlosrivas2021/debuguealo/commit/6d18e8c796d3df6bdfafe219af5f70acdbdad289))
* **terminal:** copy the selection with Ctrl+C instead of interrupting ([2e7f4a1](https://github.com/carlosrivas2021/debuguealo/commit/2e7f4a1dac12cf6e1c835cef4174c6fd86f5255b))
* **terminal:** guard POSIX reads during session shutdown ([5f8361e](https://github.com/carlosrivas2021/debuguealo/commit/5f8361ed285d1c13ab3bcc7ac1daffb16e40b4e3))
* **terminal:** treat a zombie-only process group as exited on macOS ([9314c32](https://github.com/carlosrivas2021/debuguealo/commit/9314c32fbcedc1abdfc1c04e3249710f27f4f6df))
* **terminal:** treat a zombie-only process group as exited on macOS ([cee62ea](https://github.com/carlosrivas2021/debuguealo/commit/cee62ea08b64f6741db842c39b761fb4671fb954))
* **terminal:** wait for the owned process group when closing ([91b9202](https://github.com/carlosrivas2021/debuguealo/commit/91b92028fdf2e1b7a7c646cf69c83cac628b8558))
* **tui:** add a blank row above each debug panel section title ([3296a30](https://github.com/carlosrivas2021/debuguealo/commit/3296a30bd53640add10ccfa5f52a44a8b4ca0e77))
* **tui:** add a blank row above each debug panel section title ([9d72d1c](https://github.com/carlosrivas2021/debuguealo/commit/9d72d1cdc2a440e3dc92fcea33102dfbd8884dc9))
* **tui:** highlight the active workspace area ([240736f](https://github.com/carlosrivas2021/debuguealo/commit/240736f8bb529fb9eb0ab99d973448483405429b))
* **tui:** initialize terminal screen with correct dimensions ([397bbf3](https://github.com/carlosrivas2021/debuguealo/commit/397bbf351e1fbebb1dfe50a97feb57b8cad26aa8))
* **tui:** isolate compose transcripts and align regression tests ([eff0fb8](https://github.com/carlosrivas2021/debuguealo/commit/eff0fb8601bc5a5e37bf22948b00e4a3ce5eee37))
* **tui:** keep terminal output when the pane shrinks ([2d91e9f](https://github.com/carlosrivas2021/debuguealo/commit/2d91e9fbaeca7e085da61077b3335e2397c1ced4))
* **tui:** keep terminal output when the pane shrinks ([982551d](https://github.com/carlosrivas2021/debuguealo/commit/982551d9290baeb6b52f7261f97d0069c3590297))
* **tui:** place the breakpoint editor before its first frame ([c05b488](https://github.com/carlosrivas2021/debuguealo/commit/c05b488433eace2a477713ae2bd3940d73958630))
* **tui:** release shortcuts when the focused terminal has exited ([9fd2505](https://github.com/carlosrivas2021/debuguealo/commit/9fd2505b7cfed73aa517b3e11cde90991846562e))
* **tui:** release shortcuts when the focused terminal has exited ([5ea88a3](https://github.com/carlosrivas2021/debuguealo/commit/5ea88a307770212793fdf11e2af6d6f0c2910097))
* **tui:** restore the container shell Logs button ([5bdaa3e](https://github.com/carlosrivas2021/debuguealo/commit/5bdaa3ef91cbf9d44c88236de7995e648a421b34))
* **tui:** restore the container shell Logs button ([28ee6fb](https://github.com/carlosrivas2021/debuguealo/commit/28ee6fbdb5b1bcae2cb81c786f2a9ba9be3b86ec))
* **tui:** resume after editor errors and copy via the native clipboard ([03effed](https://github.com/carlosrivas2021/debuguealo/commit/03effedc3556f45bf998eaccfca1e6f2cfcc2871))
* **tui:** show both condition and log message in breakpoint labels ([27a5e2f](https://github.com/carlosrivas2021/debuguealo/commit/27a5e2f8a373f186e64b8a2577f39b0807fa4578))
* **tui:** start Code runs under Textual's eager task factory ([77dbd69](https://github.com/carlosrivas2021/debuguealo/commit/77dbd69ea8ea5740969616a571f846643f4b1253))
* **tui:** synchronize focused inventory and fit sidebar columns ([9afe0a3](https://github.com/carlosrivas2021/debuguealo/commit/9afe0a3533ce8b7d9c4bd6a01c7986af3224e83d))


### Performance Improvements

* **docker:** reuse one inventory worker process ([06ff4bd](https://github.com/carlosrivas2021/debuguealo/commit/06ff4bd442f63b16ddba8adb9837efcedc78d4e2))
* lighter Docker polling and details-first container views ([290ccb2](https://github.com/carlosrivas2021/debuguealo/commit/290ccb2cab8c63b4bd102ff3030ce6d3f1905332))


### Documentation

* align active guides and close debugealo rename ([33dfa3a](https://github.com/carlosrivas2021/debuguealo/commit/33dfa3a21ff720ee347780cce4fad8758fa35fde))
* drop the explained NoneType terminal error from known issues ([ff96304](https://github.com/carlosrivas2021/debuguealo/commit/ff96304b0d0ecab2a0b3cf909a29bcf278ead986))
* drop the explained NoneType terminal error from known issues ([ab24c36](https://github.com/carlosrivas2021/debuguealo/commit/ab24c363fcf0b6271a1699fe56499a8752e5a023))
* install over public HTTPS without private-repo notes ([388baca](https://github.com/carlosrivas2021/debuguealo/commit/388bacadb0d7103765da029bda38f74beab629d5))
* install over public HTTPS without private-repo notes ([6cf464b](https://github.com/carlosrivas2021/debuguealo/commit/6cf464b247fc4dfa1e713e4cfb5c499c898312e5))
* mark the MVP complete and list known issues ([b0d0be2](https://github.com/carlosrivas2021/debuguealo/commit/b0d0be2a023d2e319dffbff5df010c8ddb3adf39))
* note the load-sensitive Go attach disconnect test ([a4cd1ac](https://github.com/carlosrivas2021/debuguealo/commit/a4cd1ac171040358877b6ff775878bddb8e5f4f7))
* record code project workspace designs and roadmap ([e5fce73](https://github.com/carlosrivas2021/debuguealo/commit/e5fce73ea1c2f956e68502af29420088b13f11e7))
* record the local MVP specification ([78eef1b](https://github.com/carlosrivas2021/debuguealo/commit/78eef1be367e84a99ac1b10919bbfb698cecb0df))
* refresh README with quick start, cheat sheet and demo GIFs ([f47ec4b](https://github.com/carlosrivas2021/debuguealo/commit/f47ec4b2fa0f59ce3dd68c703885cef1abfb42d3))
* **skills:** guide agents adding launch profiles ([a4ebb58](https://github.com/carlosrivas2021/debuguealo/commit/a4ebb5825885b6dcaa1cde4cffaf55ffdda5beca))
