# hca-metadata-schema (npm)

The HCA metadata data dictionaries, generated from the HCA LinkML schema in
[clevercanary/hca-validation-tools](https://github.com/clevercanary/hca-validation-tools). Don't edit the two
dictionaries by hand: `make -C shared generate-data-dictionary` writes them.

| File | Contents |
|-|-|
| `tier_1_data_dictionary.json` | The HCA Data Portal's Tier 1 dictionary: its sections, fields and order |
| `core_data_dictionary.json` | Every field of the core Dataset, Donor, Sample and Cell classes, as the HCA Atlas Tracker uses it |

```js
import tier1 from "hca-metadata-schema/tier_1_data_dictionary.json" with { type: "json" };
```

## Versions

This is the same package as `hca-metadata-schema` on PyPI, which ships the LinkML schema and its Python models. Both
are released together, at the same version, and share one changelog (`CHANGELOG.md`).

While the package is below 1.0, a breaking change raises the minor version (`0.3.x` to `0.4.0`), and anything else
raises the patch version, so a `^0.3.0` range takes fixes but not breaking changes. A breaking change to the schema is
one here too. For the dictionaries themselves, a breaking change renames or removes a key, or changes a value's type.
