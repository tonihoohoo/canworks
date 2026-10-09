# three.js 0.169.0 (vendored)

The configurator's Machine tab (Simulation view) draws the machine with
[three.js](https://threejs.org/) 0.169.0 by the three.js authors, MIT
license (see LICENSE). The files are from the npm package `three@0.169.0`
(tarball sha256 c86d0937570fb425d981e156ddf919c43dbc45d4e91fd7c8dd0de56723b3ec71):

- `build/three.module.min.js`, unchanged;
- in `addons/`, the files of `examples/jsm/` the view uses, in the same
  folders: `controls/OrbitControls.js`, `environments/RoomEnvironment.js`,
  `geometries/RoundedBoxGeometry.js`, `renderers/CSS2DRenderer.js`,
  `postprocessing/` (`EffectComposer`, `Pass`,
  `RenderPass`, `ShaderPass`, `MaskPass`, `GTAOPass`, `UnrealBloomPass`,
  `SMAAPass`, `OutputPass`) and `shaders/` (`CopyShader`, `GTAOShader`,
  `PoissonDenoiseShader`, `LuminosityHighPassShader`, `SMAAShader`,
  `OutputShader`).

One change in the addons: `from 'three'` reads
`from '../../build/three.module.min.js'`. The configurator's page allows
scripts from its own files only (no inline script), so it cannot have an
import map; the relative path does the import map's job.

One file replaced: `GTAOPass` imports `math/HashNoise.js`, a small hash
noise written for this repository, instead of `math/SimplexNoise.js` (it only
needs a fixed field of values to rotate its samples). They are served
from the configurator's own static folder, so the view needs no network.

To update: `npm pack three@<version>`, copy the same files and LICENSE here,
rewrite the `three` imports and the GTAOPass noise import the same way
(`sed -i "s#from 'three';#from '../../build/three.module.min.js';#"`) and
change the version in this file.
