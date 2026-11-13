# hca-metadata-schema (npm)

The HCA metadata data dictionaries, generated from the HCA LinkML schema in
[clevercanary/hca-validation-tools](https://github.com/clevercanary/hca-validation-tools). Don't edit these files by
hand: `make -C shared generate-data-dictionary` writes them.

| File | Contents |
|-|-|
| `tier_1_data_dictionary.json` | The HCA Data Portal's Tier 1 dictionary: its sections, fields and order |
| `core_data_dictionary.json` | Every field of the core Dataset, Donor, Sample and Cell classes, as the HCA Atlas Tracker uses it |

```js
import tier1 from "hca-metadata-schema/tier_1_data_dictionary.json" with { type: "json" };
```

## Versions

This npm package is versioned separately from the PyPI package of the same name, which ships the LinkML schema and its
Python models. Their version numbers are unrelated.

While the package is below 1.0, a breaking change raises the minor version (`0.1.x` to `0.2.0`), and anything else
raises the patch version, so a `^0.1.0` range takes fixes but not breaking changes. A breaking change renames or
removes a key, or changes a value's type. Adding a key, or changing text, is not breaking.
