from __future__ import annotations 

import re
import sys
from datetime import (
    date,
    datetime,
    time
)
from decimal import Decimal 
from enum import Enum 
from typing import (
    Any,
    ClassVar,
    Literal,
    Optional,
    Union
)

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    field_validator
)


metamodel_version = "None"
version = "0.1.0"


class ConfiguredBaseModel(BaseModel):
    model_config = ConfigDict(
        validate_assignment = True,
        validate_default = True,
        extra = "forbid",
        arbitrary_types_allowed = True,
        use_enum_values = True,
        strict = False,
    )
    pass




class LinkMLMeta(RootModel):
    root: dict[str, Any] = {}
    model_config = ConfigDict(frozen=True)

    def __getattr__(self, key:str):
        return getattr(self.root, key)

    def __getitem__(self, key:str):
        return self.root[key]

    def __setitem__(self, key:str, value):
        self.root[key] = value

    def __contains__(self, key:str) -> bool:
        return key in self.root


linkml_meta = LinkMLMeta({'default_prefix': 'hca',
     'default_range': 'string',
     'description': 'Core schema for validating Human Cell Atlas (HCA) data',
     'id': 'https://github.com/clevercanary/hca-validation-tools/schema/core',
     'imports': ['linkml:types', 'dataset', 'donor', 'sample', 'cell'],
     'license': 'MIT',
     'name': 'hca-validation-core',
     'prefixes': {'hca': {'prefix_prefix': 'hca',
                          'prefix_reference': 'https://github.com/clevercanary/hca-validation-tools/schema/'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'src/hca_validation/schema/core.yaml',
     'title': 'HCA Validation Core Schema'} )

class ReferenceGenomeEnum(str, Enum):
    GRCh38 = "GRCh38"
    """
    Human reference genome version 38
    """
    GRCh37 = "GRCh37"
    """
    Human reference genome version 37
    """
    GRCm39 = "GRCm39"
    """
    Mouse reference genome version 39
    """
    GRCm38 = "GRCm38"
    """
    Mouse reference genome version 38
    """
    GRCm37 = "GRCm37"
    """
    Mouse reference genome version 37
    """
    not_applicable = "not applicable"
    """
    No reference genome was used
    """


class IntronInclusionEnum(str, Enum):
    yes = "yes"
    """
    Introns were included
    """
    no = "no"
    """
    Introns were not included
    """


class SequencedFragmentEnum(str, Enum):
    number_3_prime_tag = "3 prime tag"
    """
    3' end of the transcript
    """
    number_5_prime_tag = "5 prime tag"
    """
    5' end of the transcript
    """
    probe_based = "probe-based"
    """
    Probe-based sequencing
    """
    full_length = "full length"
    """
    Entire transcript
    """
    not_applicable = "not applicable"
    """
    Not applicable to this dataset
    """



class Dataset(ConfiguredBaseModel):
    """
    A collection of data from a single experiment or study in the Human Cell Atlas
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/dataset'})

    study_pi: list[str] = Field(default=..., title="Study Pi", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last '
                                      'Name,MiddleInitial, FirstName format',
                       'value': '["Teichmann,Sarah,A."]'}]} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor.  The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'cxg': {'tag': 'cxg', 'value': 'batch_condition'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'cxg': {'tag': 'cxg', 'value': 'default_embedding'}},
         'domain_of': ['Dataset']} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols/ontologies/efo/terms?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term Id", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'}},
         'comments': ['Major source of batch effect and dataset filtering criterion'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0009922'}],
         'notes': ['This must be an EFO term and either:\n'
                   '- "EFO:0002772" for assay by molecule or preferably its most '
                   'accurate child\n'
                   '- "EFO:0010183" for single cell library construction or preferably '
                   'its most accurate child\n'
                   '- An assay based on 10X Genomics products should either be '
                   '"EFO:0008995" for 10x technology or preferably its most accurate '
                   'child. \n'
                   "- An assay based on SMART (Switching Mechanism at the 5' end of "
                   'the RNA Template) or SMARTer technology SHOULD either be '
                   '"EFO:0010184" for Smart-like or preferably its most accurate '
                   'child.\n'
                   'Recommended:\n'
                   '- 10x 3\' v2 "EFO:0009899"\n'
                   '- 10x 3\' v3 "EFO:0009922"\n'
                   '- 10x 5\' v1 "EFO:0011025"\n'
                   '- 10x 5\' v2 "EFO:0009900"\n'
                   '- Smart-seq2 "EFO:0008931"\n'
                   '- Visium Spatial Gene Expression "EFO:0010961"\n']} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCm37'}, {'value': 'GRCh37'}]} })
    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cellranger_8.0.0'}]} })
    intron_inclusion: Optional[IntronInclusionEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40
""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample.  Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.
""", json_schema_extra = { "linkml_meta": {'alias': 'comments', 'domain_of': ['Dataset']} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol;  or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.
""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    title: str = Field(default=..., title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection.  It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata  such as a different assay to disambiguate it from other datasets in the collection.
""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'cxg': {'tag': 'cxg', 'value': 'title'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': "Cells of the adult human heart collection is 'All — "
                                "Cells of the adult human heart'"}]} })


class Donor(ConfiguredBaseModel):
    """
    An individual organism from which biological samples have been derived
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/donor'})

    pass


class Sample(ConfiguredBaseModel):
    """
    A biological sample derived from a donor or another sample
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/sample'})

    pass


class Cell(ConfiguredBaseModel):
    """
    A single cell derived from a sample
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/cell'})

    pass


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Dataset.model_rebuild()
Donor.model_rebuild()
Sample.model_rebuild()
Cell.model_rebuild()

