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
     'imports': ['linkml:types',
                 'dataset',
                 'bionetwork/adipose',
                 'bionetwork/gut',
                 'donor',
                 'sample',
                 'cell'],
     'license': 'MIT',
     'name': 'hca-validation-core',
     'prefixes': {'hca': {'prefix_prefix': 'hca',
                          'prefix_reference': 'https://github.com/clevercanary/hca-validation-tools/schema/'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'src/hca_validation/schema/core.yaml',
     'title': 'HCA Validation Core Schema'} )

class ReferenceGenomeEnum(str, Enum):
    GRCh37 = "GRCh37"
    """
    Human reference genome version 37
    """
    GRCh38 = "GRCh38"
    """
    Human reference genome version 38
    """
    GRCm37 = "GRCm37"
    """
    Mouse reference genome version 37
    """
    GRCm38 = "GRCm38"
    """
    Mouse reference genome version 38
    """
    GRCm39 = "GRCm39"
    """
    Mouse reference genome version 39
    """
    not_applicable = "not applicable"
    """
    No reference genome was used
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
    full_length = "full length"
    """
    Entire transcript
    """
    not_applicable = "not applicable"
    """
    Not applicable to this dataset
    """
    probe_based = "probe-based"
    """
    Probe-based sequencing
    """


class YesNoEnum(str, Enum):
    no = "no"
    """
    Negative / false
    """
    yes = "yes"
    """
    Affirmative / true
    """


class RadialTissueTerm(str, Enum):
    EPI = "EPI"
    LP = "LP"
    MUSC = "MUSC"
    EPI_LP = "EPI_LP"
    LP_MUSC = "LP_MUSC"
    EPI_LP_MUSC = "EPI_LP_MUSC"
    MLN = "MLN"
    SUB = "SUB"
    Peyers_patch = "Peyers patch"
    Mucosal_ILF = "Mucosal ILF"
    Submucosal_ILF = "Submucosal ILF"
    WM = "WM"


class SampleCollectionMethod(str, Enum):
    brush = "brush"
    scraping = "scraping"
    biopsy = "biopsy"
    surgical_resection = "surgical_resection"
    blood_draw = "blood_draw"
    body_fluid = "body_fluid"
    other = "other"


class TissueType(str, Enum):
    tissue = "tissue"
    organoid = "organoid"
    cell_culture = "cell culture"


class SuspensionType(str, Enum):
    cell = "cell"
    nucleus = "nucleus"
    na = "na"


class SampledSiteCondition(str, Enum):
    healthy = "healthy"
    diseased = "diseased"
    adjacent = "adjacent"


class SamplePreservationMethod(str, Enum):
    ambient_temperature = "ambient temperature"
    cut_slide = "cut slide"
    fresh = "fresh"
    frozen_at__70C = "frozen at -70C"
    frozen_at__80C = "frozen at -80C"
    frozen_at__150C = "frozen at -150C"
    frozen_in_liquid_nitrogen = "frozen in liquid nitrogen"
    frozen_in_vapor_phase = "frozen in vapor phase"
    paraffin_block = "paraffin block"
    RNAlater_at_4C = "RNAlater at 4C"
    RNAlater_at_25C = "RNAlater at 25C"
    RNAlater_at__20C = "RNAlater at -20C"
    other = "other"


class SampleSource(str, Enum):
    surgical_donor = "surgical_donor"
    postmortem_donor = "postmortem_donor"
    living_organ_donor = "living_organ_donor"


class MannerOfDeath(str, Enum):
    number_1 = "1"
    number_2 = "2"
    number_3 = "3"
    number_4 = "4"
    number_0 = "0"
    unknown = "unknown"
    not_applicable = "not_applicable"


class DevelopmentStage(str, Enum):
    HsapDvCOLON0000003 = "HsapDv:0000003"
    HsapDvCOLON0000046 = "HsapDv:0000046"
    HsapDvCOLON0000264 = "HsapDv:0000264"
    HsapDvCOLON0000268 = "HsapDv:0000268"
    HsapDvCOLON0000237 = "HsapDv:0000237"
    HsapDvCOLON0000238 = "HsapDv:0000238"
    HsapDvCOLON0000239 = "HsapDv:0000239"
    HsapDvCOLON0000240 = "HsapDv:0000240"
    HsapDvCOLON0000241 = "HsapDv:0000241"
    HsapDvCOLON0000242 = "HsapDv:0000242"
    HsapDvCOLON0000243 = "HsapDv:0000243"
    MmusDvCOLON0000001 = "MmusDv:0000001"
    MmusDvCOLON0000002 = "MmusDv:0000002"
    unknown = "unknown"


class Organism(str, Enum):
    NCBITaxonCOLON9606 = "NCBITaxon:9606"
    NCBITaxonCOLON10090 = "NCBITaxon:10090"



class Dataset(ConfiguredBaseModel):
    """
    A collection of data from a single experiment or study in the Human Cell Atlas
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/dataset',
         'slot_usage': {'dataset_id': {'identifier': True,
                                       'name': 'dataset_id',
                                       'range': 'string'}}})

    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cellranger_8.0.0'}]} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term Id", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'}},
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
                   'child.\n'
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
    assay_ontology_term: Optional[str] = Field(default=None, title="Assay Ontology Term", description="""Deprecated placeholder for assay ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term',
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor.  The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'batch_condition'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample.  Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.
""", json_schema_extra = { "linkml_meta": {'alias': 'comments',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    consortia: Optional[str] = Field(default=None, title="Consortia", description="""Deprecated placeholder for consortia information.""", json_schema_extra = { "linkml_meta": {'alias': 'consortia', 'domain_of': ['Dataset'], 'is_a': 'deprecated_slot'} })
    contact_email: str = Field(default=..., title="Contact Email", description="""Contact name and email of the submitting person""", json_schema_extra = { "linkml_meta": {'alias': 'contact_email', 'domain_of': ['Dataset']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'default_embedding'}},
         'domain_of': ['Dataset']} })
    description: str = Field(default=..., title="Description", description="""Short description of the dataset""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40
""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    intron_inclusion: Optional[YesNoEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}, {'value': 'no'}]} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol;  or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.
""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    publication_doi: Optional[str] = Field(default=None, title="Publication DOI", description="""The publication digital object identifier (doi) for the protocol. If no pre-print nor publication exists, please write 'not applicable'.
""", json_schema_extra = { "linkml_meta": {'alias': 'publication_doi',
         'domain_of': ['Dataset'],
         'examples': [{'value': '10.1016/j.cell.2016.07.054'}]} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCm37'}, {'value': 'GRCh37'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols/ontologies/efo/terms?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    study_pi: list[str] = Field(default=..., title="Study Pi", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last '
                                      'Name,MiddleInitial, FirstName format',
                       'value': '["Teichmann,Sarah,A."]'}]} })
    title: Optional[str] = Field(default=None, title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection.  It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata  such as a different assay to disambiguate it from other datasets in the collection.
""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'title'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': "Cells of the adult human heart collection is 'All — "
                                "Cells of the adult human heart'"}],
         'is_a': 'deprecated_slot'} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })


class AdiposeDataset(Dataset):
    """
    Dataset with Adipose BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/adipose'})

    ambient_count_correction: str = Field(default=..., title="Ambient Count Correction", description="""Method used to correct ambient RNA contamination in single-cell data.""", json_schema_extra = { "linkml_meta": {'alias': 'ambient_count_correction',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['AdiposeDataset', 'GutDataset'],
         'examples': [{'value': 'none'}, {'value': 'soupx'}, {'value': 'cellbender'}]} })
    doublet_detection: str = Field(default=..., title="Doublet Detection", description="""Was doublet detection software used during CELLxGENE processing? If so, which software?""", json_schema_extra = { "linkml_meta": {'alias': 'doublet_detection',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['AdiposeDataset', 'GutDataset'],
         'examples': [{'value': 'none'},
                      {'value': 'doublet_finder'},
                      {'value': 'manual'}]} })
    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cellranger_8.0.0'}]} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term Id", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'}},
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
                   'child.\n'
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
    assay_ontology_term: Optional[str] = Field(default=None, title="Assay Ontology Term", description="""Deprecated placeholder for assay ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term',
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor.  The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'batch_condition'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample.  Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.
""", json_schema_extra = { "linkml_meta": {'alias': 'comments',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    consortia: Optional[str] = Field(default=None, title="Consortia", description="""Deprecated placeholder for consortia information.""", json_schema_extra = { "linkml_meta": {'alias': 'consortia', 'domain_of': ['Dataset'], 'is_a': 'deprecated_slot'} })
    contact_email: str = Field(default=..., title="Contact Email", description="""Contact name and email of the submitting person""", json_schema_extra = { "linkml_meta": {'alias': 'contact_email', 'domain_of': ['Dataset']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'default_embedding'}},
         'domain_of': ['Dataset']} })
    description: str = Field(default=..., title="Description", description="""Short description of the dataset""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40
""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    intron_inclusion: Optional[YesNoEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}, {'value': 'no'}]} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol;  or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.
""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    publication_doi: Optional[str] = Field(default=None, title="Publication DOI", description="""The publication digital object identifier (doi) for the protocol. If no pre-print nor publication exists, please write 'not applicable'.
""", json_schema_extra = { "linkml_meta": {'alias': 'publication_doi',
         'domain_of': ['Dataset'],
         'examples': [{'value': '10.1016/j.cell.2016.07.054'}]} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCm37'}, {'value': 'GRCh37'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols/ontologies/efo/terms?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    study_pi: list[str] = Field(default=..., title="Study Pi", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last '
                                      'Name,MiddleInitial, FirstName format',
                       'value': '["Teichmann,Sarah,A."]'}]} })
    title: Optional[str] = Field(default=None, title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection.  It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata  such as a different assay to disambiguate it from other datasets in the collection.
""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'title'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': "Cells of the adult human heart collection is 'All — "
                                "Cells of the adult human heart'"}],
         'is_a': 'deprecated_slot'} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })


class Donor(ConfiguredBaseModel):
    """
    An individual organism from which biological samples have been derived
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/donor',
         'slot_usage': {'donor_id': {'annotations': {'annDataLocation': {'tag': 'annDataLocation',
                                                                         'value': 'obs'},
                                                     'cxg': {'tag': 'cxg',
                                                             'value': 'donor_id'},
                                                     'tier': {'tag': 'tier',
                                                              'value': 'Tier 1'}},
                                     'identifier': True,
                                     'name': 'donor_id',
                                     'range': 'string'}}})

    donor_id: str = Field(default=..., title="Donor ID", description="""This must be free-text that identifies a unique individual that data were derived from.""", json_schema_extra = { "linkml_meta": {'alias': 'donor_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'donor_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of biological variation of the data. It is '
                      'strongly recommended that this identifier be designed so that '
                      'it is unique to: a given individual within the collection of '
                      'datasets that includes this dataset, and a given individual '
                      'across all collections in CELLxGENE Discover. It is strongly '
                      'recommended that "pooled" be used for observations from a '
                      'sample of multiple individuals that were not confidently '
                      'assigned to a single individual through demultiplexing. It is '
                      'strongly recommended that "unknown" ONLY be used for '
                      'observations in a dataset when it is not known which '
                      'observations are from the same individual.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1; MM_donor_1; LR_donor_2'}]} })
    organism_ontology_term_id: Organism = Field(default=..., title="Organism Ontology Term ID", description="""The name given to the type of organism, collected in NCBITaxon:0000 format.""", json_schema_extra = { "linkml_meta": {'alias': 'organism_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'organism_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Donor'],
         'notes': ['"NCBITaxon:9606" for Homo sapiens or "NCBITaxon:10090" for Mus '
                   'musculus.']} })
    sex_ontology_term_id: str = Field(default=..., title="Sex Ontology Term ID", description="""Reported sex of the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sex_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'sex_ontology_term_id'}},
         'domain_of': ['Donor'],
         'examples': [{'description': 'female', 'value': 'PATO:0000383'},
                      {'description': 'male', 'value': 'PATO:0000384'}],
         'notes': ['This must be a child of PATO:0001894 for phenotypic sex or '
                   '"unknown" if unavailable.\n']} })
    sex_ontology_term: Optional[str] = Field(default=None, title="Sex Ontology Term", description="""Deprecated placeholder for sex ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'sex_ontology_term',
         'domain_of': ['Donor'],
         'is_a': 'deprecated_slot'} })
    manner_of_death: MannerOfDeath = Field(default=..., title="Manner of Death", description="""Manner of death classification based on the Hardy Scale or \"unknown\" or \"not applicable\":
* Category 1 = Violent and fast death — deaths due to accident, blunt force trauma or suicide, terminal phase < 10 min.
* Category 2 = Fast death of natural causes — sudden unexpected deaths of reasonably healthy people, terminal phase < 1 h.
* Category 3 = Intermediate death — terminal phase 1–24 h, patients ill but death unexpected.
* Category 4 = Slow death — terminal phase > 1 day (e.g. cancer, chronic pulmonary disease).
* Category 0 = Ventilator case — on a ventilator immediately before death.
* Unknown = The cause of death is unknown.
* Not applicable = Subject is alive.
[Leave blank for embryonic/fetal tissue.]
""", json_schema_extra = { "linkml_meta": {'alias': 'manner_of_death',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Donor'],
         'examples': [{'value': '1'}],
         'notes': ['1; 2; 3; 4; 0; unknown; not applicable']} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })


class Sample(ConfiguredBaseModel):
    """
    A biological sample derived from a donor or another sample
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/sample',
         'slot_usage': {'sample_id': {'annotations': {'annDataLocation': {'tag': 'annDataLocation',
                                                                          'value': 'obs'},
                                                      'tier': {'tag': 'tier',
                                                               'value': 'Tier 1'}},
                                      'identifier': True,
                                      'name': 'sample_id',
                                      'range': 'string'}}})

    sample_id: str = Field(default=..., title="Sample ID", description="""Identification number of the sample. This is the fundamental unit of sampling the tissue (the specimen taken from the subject), which can be the same as the 'subject_ID', but is often different if multiple samples are taken from the same subject. Note: this is NOT a unit of multiplexing of donor samples, which should be stored in \"library\".""", json_schema_extra = { "linkml_meta": {'alias': 'sample_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'SC24; SC25; SC28'}]} })
    donor_id: str = Field(default=..., title="Donor ID", description="""This must be free-text that identifies a unique individual that data were derived from.""", json_schema_extra = { "linkml_meta": {'alias': 'donor_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'donor_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of biological variation of the data. It is '
                      'strongly recommended that this identifier be designed so that '
                      'it is unique to: a given individual within the collection of '
                      'datasets that includes this dataset, and a given individual '
                      'across all collections in CELLxGENE Discover. It is strongly '
                      'recommended that "pooled" be used for observations from a '
                      'sample of multiple individuals that were not confidently '
                      'assigned to a single individual through demultiplexing. It is '
                      'strongly recommended that "unknown" ONLY be used for '
                      'observations in a dataset when it is not known which '
                      'observations are from the same individual.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1; MM_donor_1; LR_donor_2'}]} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })
    author_batch_notes: Optional[str] = Field(default=None, title="Author Batch Notes", description="""Encoding of author knowledge on any further information related to likely batch effects.""", json_schema_extra = { "linkml_meta": {'alias': 'author_batch_notes',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Space for author intuition of batch effects in their dataset'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'Batch run by different personnel on different days'}]} })
    age_range: Optional[str] = Field(default=None, title="Age Range", description="""Deprecated placeholder for age range metadata.""", json_schema_extra = { "linkml_meta": {'alias': 'age_range', 'domain_of': ['Sample'], 'is_a': 'deprecated_slot'} })
    cell_number_loaded: Optional[int] = Field(default=None, title="Cell Number Loaded", description="""Estimated number of cells loaded for library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_number_loaded',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Can explain the number of doublets found in samples'],
         'domain_of': ['Sample'],
         'examples': [{'value': '5000; 4000'}]} })
    cell_viability_percentage: Optional[Union[Decimal, str]] = Field(default=None, title="Cell Viability Percentage", description="""If measured, per sample cell viability before library preparation (as a percentage).""", json_schema_extra = { "linkml_meta": {'alias': 'cell_viability_percentage',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'any_of': [{'range': 'decimal'}, {'range': 'string'}],
         'comments': ['Is a measure of sample quality that could be used to explain '
                      'outlier samples'],
         'domain_of': ['Sample'],
         'examples': [{'value': '88; 95; 93.5'}, {'value': 'unknown'}]} })
    cell_enrichment: str = Field(default=..., title="Cell Enrichment", description="""Specifies the cell types targeted for enrichment or depletion beyond the selection of live cells.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_enrichment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'CL:0000057+'}],
         'notes': ['This must be a Cell Ontology (CL) term '
                   '(http://www.ebi.ac.uk/ols4/ontologies/cl). For cells that are '
                   "enriched, list the CL code followed by a '+'. For cells that were "
                   "depleted, list the CL code followed by a '-'. If no enrichment or "
                   "depletion occurred, please use 'na' (not applicable)"]} })
    development_stage_ontology_term_id: DevelopmentStage = Field(default=..., title="Development Stage Ontology Term ID", description="""Age of the subject.""", json_schema_extra = { "linkml_meta": {'alias': 'development_stage_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg',
                                 'value': 'development_stage_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'HsapDv:0000237'}],
         'notes': ['If organism_ontolology_term_id is "NCBITaxon:9606" for Homo '
                   'sapiens, this should be an HsapDv term. If '
                   'organism_ontolology_term_id is "NCBITaxon:10090" for Mus musculus, '
                   'this should be an MmusDv term. Refer to broader age bracket terms '
                   'as needed.']} })
    disease_ontology_term_id: str = Field(default=..., title="Disease Ontology Term ID", description="""Disease, if expected to impact the sample.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'disease_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'MONDO:0005385'}, {'value': 'PATO:0000461'}],
         'notes': ['This must be a MONDO term or "PATO:0000461" for normal or '
                   'healthy.\n'
                   '\n'
                   'Requirements for data contributors adhering to GDPR or like '
                   'standards: In the case of disease, HCA requests that you submit a '
                   'higher order ontology term - this is especially important in the '
                   'case of rare disease.\n']} })
    disease_ontology_term: Optional[str] = Field(default=None, title="Disease Ontology Term", description="""Deprecated placeholder for disease ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term',
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })
    institute: str = Field(default=..., title="Institute", description="""Institution where the samples were processed.""", json_schema_extra = { "linkml_meta": {'alias': 'institute',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To be able to link to other studies from the same institution '
                      'as sometimes samples from different labs in the same institute '
                      'are processed via similar core facilities. Thus batch effects '
                      'may be smaller for datasets from the same institute even if '
                      'other factors differ.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'EMBL-EBI; Genome Institute of Singapore'}]} })
    is_primary_data: Optional[str] = Field(default=None, title="Is Primary Data", description="""Deprecated placeholder indicating whether sample represents primary data.""", json_schema_extra = { "linkml_meta": {'alias': 'is_primary_data', 'domain_of': ['Sample'], 'is_a': 'deprecated_slot'} })
    library_id: str = Field(default=..., title="Library ID", description="""The unique ID that is used to track libraries in the investigator's institution (should align with the publication).""", json_schema_extra = { "linkml_meta": {'alias': 'library_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['A way to track the unit of data generation. This should include '
                      'sample pooling'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'A24; NK_healthy_001'}]} })
    library_id_repository: Optional[str] = Field(default=None, title="Library ID Repository", description="""The unique ID used to track libraries from one of the following public data repositories: EGAX*, GSM*, SRX*, ERX*, DRX, HRX, CRX.""", json_schema_extra = { "linkml_meta": {'alias': 'library_id_repository',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Links a dataset back to the source from which it was ingested, '
                      'optional only if this is the same as the library_id.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'GSM1684095'}]} })
    library_preparation_batch: str = Field(default=..., title="Library Preparation Batch", description="""Indicating which samples' libraries were prepared in the same chip/plate/etc., e.g. batch1, batch2.""", json_schema_extra = { "linkml_meta": {'alias': 'library_preparation_batch',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Sample preparation is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'batch01; batch02'}]} })
    library_sequencing_run: str = Field(default=..., title="Library Sequencing Run", description="""The identifier (or accession number) that indicates which samples' libraries were sequenced in the same run.""", json_schema_extra = { "linkml_meta": {'alias': 'library_sequencing_run',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Library sequencing is a major source of batch effects'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'run1; NV0087'}]} })
    sample_collection_method: SampleCollectionMethod = Field(default=..., title="Sample Collection Method", description="""The method the sample was physically obtained from the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_method',
         'domain_of': ['Sample'],
         'notes': ['brush; scraping; biopsy; surgical resection; blood draw; body '
                   'fluid; other']} })
    sample_collection_year: Optional[str] = Field(default=None, title="Sample Collection Year", description="""Year of sample collection. Should not be detailed further (to exact month and day), to prevent identifiability.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_year',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['May explain whether a dataset was separated into smaller '
                      'batches.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '2018'}]} })
    sample_collection_site: Optional[str] = Field(default=None, title="Sample Collection Site", description="""The pseudonymised name of the site where the sample was collected.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_site',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To understand whether the collection site contributes to batch '
                      'effects. It is strongly recommended that this identifier be '
                      'designed so that it is unique to a given site within the '
                      'collection of datasets that includes this site (for example, '
                      "the labels 'site1', 'site2' may appear in other datasets thus "
                      'rendering them indistinguishable).'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'AIDA_site_1; AIDA_site_2'}]} })
    sample_collection_relative_time_point: Optional[str] = Field(default=None, title="Sample Collection Relative Time Point", description="""Time point when the sample was collected. This field is only needed if multiple samples from the same subject are available and collected at different time points. Sample collection dates (e.g. 23/09/22) cannot be used due to patient data protection, only relative time points should be used here (e.g. day3).""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_relative_time_point',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Explains variability in the data between samples from the same '
                      'subject.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'sampleX_day1'}]} })
    tissue_free_text: Optional[str] = Field(default=None, title="Tissue Free Text", description="""The detailed anatomical location of the sample - this does not have to tie to an ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_free_text',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To help the integration team understand the anatomical location '
                      'of the sample, specifically to solve the problem when the '
                      'UBERON ontology terms are insufficiently precise.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'terminal ileum'}]} })
    tissue_type: TissueType = Field(default=..., title="Tissue Type", description="""Whether the tissue is \"tissue\", \"organoid\", or \"cell culture\".""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'tissue'}],
         'notes': ['tissue; organoid; cell culture']} })
    tissue_ontology_term_id: str = Field(default=..., title="Tissue Ontology Term ID", description="""The detailed anatomical location of the sample, please provide a specific UBERON term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'UBERON:0001828'}, {'value': 'UBERON:0000966'}],
         'notes': ['If tissue_type is "tissue" or "organoid", this must be the most '
                   'accurate child of UBERON:0001062 for anatomical entity. If '
                   'tissue_type is "cell culture" this must follow the requirements '
                   'for cell_type_ontology_term_id.\n']} })
    suspension_type: SuspensionType = Field(default=..., title="Suspension Type", description="""Specifies whether the sample contains single cells or single nuclei data.""", json_schema_extra = { "linkml_meta": {'alias': 'suspension_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'suspension_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'cell'}],
         'notes': ['This must be "cell", "nucleus", or "na".\n'
                   'This must be the correct type for the corresponding assay:\n'
                   '* 10x transcription profiling [EFO:0030080] and its children = '
                   '"cell" or "nucleus"\n'
                   '* ATAC-seq [EFO:0007045] and its children = "nucleus"\n'
                   '* BD Rhapsody Whole Transcriptome Analysis [EFO:0700003] = "cell"\n'
                   '* BD Rhapsody Targeted mRNA [EFO:0700004] = "cell"\n'
                   '* CEL-seq2 [EFO:0010010] = "cell" or "nucleus"\n'
                   '* CITE-seq [EFO:0009294] and its children = "cell"\n'
                   '* DroNc-seq [EFO:0008720] = "nucleus"\n'
                   '* Drop-seq [EFO:0008722] = "cell" or "nucleus"\n'
                   '* GEXSCOPE technology [EFO:0700011] = "cell" or "nucleus"\n'
                   '* inDrop [EFO:0008780] = "cell" or "nucleus"\n']} })
    sampled_site_condition: SampledSiteCondition = Field(default=..., title="Sampled Site Condition", description="""Whether the site is considered healthy, diseased or adjacent to disease.""", json_schema_extra = { "linkml_meta": {'alias': 'sampled_site_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'healthy'}],
         'notes': ['healthy; diseased; adjacent']} })
    sample_preservation_method: SamplePreservationMethod = Field(default=..., title="Sample Preservation Method", description="""Indicating if tissue was frozen, or not, at any point before library preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_preservation_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'fresh'}],
         'notes': ['ambient temperature; cut slide; fresh; frozen at -70C; frozen at '
                   '-80C; frozen at -150C; frozen in liquid nitrogen; frozen in vapor '
                   'phase; paraffin block; RNAlater at 4C; RNAlater at 25C; RNAlater '
                   'at -20C; other']} })
    sample_source: SampleSource = Field(default=..., title="Sample Source", description="""The study subgroup that the participant belongs to, indicating whether the participant was a surgical donor, a postmortem donor, or an organ donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_source',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'surgical donor'}],
         'notes': ['surgical donor; postmortem donor; living organ donor']} })
    tissue_ontology_term: Optional[str] = Field(default=None, title="Tissue Ontology Term", description="""Deprecated placeholder for tissue ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term',
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })


class AdiposeSample(Sample):
    """
    Sample with Adipose BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/adipose'})

    dissociation_protocol: str = Field(default=..., title="Dissociation Protocol", description="""Dissociation chemicals used during sample preparation""", json_schema_extra = { "linkml_meta": {'alias': 'dissociation_protocol',
         'domain_of': ['AdiposeSample', 'GutSample'],
         'notes': ['trypsin; trypLE; collagenase']} })
    sample_id: str = Field(default=..., title="Sample ID", description="""Identification number of the sample. This is the fundamental unit of sampling the tissue (the specimen taken from the subject), which can be the same as the 'subject_ID', but is often different if multiple samples are taken from the same subject. Note: this is NOT a unit of multiplexing of donor samples, which should be stored in \"library\".""", json_schema_extra = { "linkml_meta": {'alias': 'sample_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'SC24; SC25; SC28'}]} })
    donor_id: str = Field(default=..., title="Donor ID", description="""This must be free-text that identifies a unique individual that data were derived from.""", json_schema_extra = { "linkml_meta": {'alias': 'donor_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'donor_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of biological variation of the data. It is '
                      'strongly recommended that this identifier be designed so that '
                      'it is unique to: a given individual within the collection of '
                      'datasets that includes this dataset, and a given individual '
                      'across all collections in CELLxGENE Discover. It is strongly '
                      'recommended that "pooled" be used for observations from a '
                      'sample of multiple individuals that were not confidently '
                      'assigned to a single individual through demultiplexing. It is '
                      'strongly recommended that "unknown" ONLY be used for '
                      'observations in a dataset when it is not known which '
                      'observations are from the same individual.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1; MM_donor_1; LR_donor_2'}]} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })
    author_batch_notes: Optional[str] = Field(default=None, title="Author Batch Notes", description="""Encoding of author knowledge on any further information related to likely batch effects.""", json_schema_extra = { "linkml_meta": {'alias': 'author_batch_notes',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Space for author intuition of batch effects in their dataset'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'Batch run by different personnel on different days'}]} })
    age_range: Optional[str] = Field(default=None, title="Age Range", description="""Deprecated placeholder for age range metadata.""", json_schema_extra = { "linkml_meta": {'alias': 'age_range', 'domain_of': ['Sample'], 'is_a': 'deprecated_slot'} })
    cell_number_loaded: Optional[int] = Field(default=None, title="Cell Number Loaded", description="""Estimated number of cells loaded for library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_number_loaded',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Can explain the number of doublets found in samples'],
         'domain_of': ['Sample'],
         'examples': [{'value': '5000; 4000'}]} })
    cell_viability_percentage: Optional[Union[Decimal, str]] = Field(default=None, title="Cell Viability Percentage", description="""If measured, per sample cell viability before library preparation (as a percentage).""", json_schema_extra = { "linkml_meta": {'alias': 'cell_viability_percentage',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'any_of': [{'range': 'decimal'}, {'range': 'string'}],
         'comments': ['Is a measure of sample quality that could be used to explain '
                      'outlier samples'],
         'domain_of': ['Sample'],
         'examples': [{'value': '88; 95; 93.5'}, {'value': 'unknown'}]} })
    cell_enrichment: str = Field(default=..., title="Cell Enrichment", description="""Specifies the cell types targeted for enrichment or depletion beyond the selection of live cells.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_enrichment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'CL:0000057+'}],
         'notes': ['This must be a Cell Ontology (CL) term '
                   '(http://www.ebi.ac.uk/ols4/ontologies/cl). For cells that are '
                   "enriched, list the CL code followed by a '+'. For cells that were "
                   "depleted, list the CL code followed by a '-'. If no enrichment or "
                   "depletion occurred, please use 'na' (not applicable)"]} })
    development_stage_ontology_term_id: DevelopmentStage = Field(default=..., title="Development Stage Ontology Term ID", description="""Age of the subject.""", json_schema_extra = { "linkml_meta": {'alias': 'development_stage_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg',
                                 'value': 'development_stage_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'HsapDv:0000237'}],
         'notes': ['If organism_ontolology_term_id is "NCBITaxon:9606" for Homo '
                   'sapiens, this should be an HsapDv term. If '
                   'organism_ontolology_term_id is "NCBITaxon:10090" for Mus musculus, '
                   'this should be an MmusDv term. Refer to broader age bracket terms '
                   'as needed.']} })
    disease_ontology_term_id: str = Field(default=..., title="Disease Ontology Term ID", description="""Disease, if expected to impact the sample.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'disease_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'MONDO:0005385'}, {'value': 'PATO:0000461'}],
         'notes': ['This must be a MONDO term or "PATO:0000461" for normal or '
                   'healthy.\n'
                   '\n'
                   'Requirements for data contributors adhering to GDPR or like '
                   'standards: In the case of disease, HCA requests that you submit a '
                   'higher order ontology term - this is especially important in the '
                   'case of rare disease.\n']} })
    disease_ontology_term: Optional[str] = Field(default=None, title="Disease Ontology Term", description="""Deprecated placeholder for disease ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term',
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })
    institute: str = Field(default=..., title="Institute", description="""Institution where the samples were processed.""", json_schema_extra = { "linkml_meta": {'alias': 'institute',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To be able to link to other studies from the same institution '
                      'as sometimes samples from different labs in the same institute '
                      'are processed via similar core facilities. Thus batch effects '
                      'may be smaller for datasets from the same institute even if '
                      'other factors differ.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'EMBL-EBI; Genome Institute of Singapore'}]} })
    is_primary_data: Optional[str] = Field(default=None, title="Is Primary Data", description="""Deprecated placeholder indicating whether sample represents primary data.""", json_schema_extra = { "linkml_meta": {'alias': 'is_primary_data', 'domain_of': ['Sample'], 'is_a': 'deprecated_slot'} })
    library_id: str = Field(default=..., title="Library ID", description="""The unique ID that is used to track libraries in the investigator's institution (should align with the publication).""", json_schema_extra = { "linkml_meta": {'alias': 'library_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['A way to track the unit of data generation. This should include '
                      'sample pooling'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'A24; NK_healthy_001'}]} })
    library_id_repository: Optional[str] = Field(default=None, title="Library ID Repository", description="""The unique ID used to track libraries from one of the following public data repositories: EGAX*, GSM*, SRX*, ERX*, DRX, HRX, CRX.""", json_schema_extra = { "linkml_meta": {'alias': 'library_id_repository',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Links a dataset back to the source from which it was ingested, '
                      'optional only if this is the same as the library_id.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'GSM1684095'}]} })
    library_preparation_batch: str = Field(default=..., title="Library Preparation Batch", description="""Indicating which samples' libraries were prepared in the same chip/plate/etc., e.g. batch1, batch2.""", json_schema_extra = { "linkml_meta": {'alias': 'library_preparation_batch',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Sample preparation is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'batch01; batch02'}]} })
    library_sequencing_run: str = Field(default=..., title="Library Sequencing Run", description="""The identifier (or accession number) that indicates which samples' libraries were sequenced in the same run.""", json_schema_extra = { "linkml_meta": {'alias': 'library_sequencing_run',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Library sequencing is a major source of batch effects'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'run1; NV0087'}]} })
    sample_collection_method: SampleCollectionMethod = Field(default=..., title="Sample Collection Method", description="""The method the sample was physically obtained from the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_method',
         'domain_of': ['Sample'],
         'notes': ['brush; scraping; biopsy; surgical resection; blood draw; body '
                   'fluid; other']} })
    sample_collection_year: Optional[str] = Field(default=None, title="Sample Collection Year", description="""Year of sample collection. Should not be detailed further (to exact month and day), to prevent identifiability.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_year',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['May explain whether a dataset was separated into smaller '
                      'batches.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '2018'}]} })
    sample_collection_site: Optional[str] = Field(default=None, title="Sample Collection Site", description="""The pseudonymised name of the site where the sample was collected.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_site',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To understand whether the collection site contributes to batch '
                      'effects. It is strongly recommended that this identifier be '
                      'designed so that it is unique to a given site within the '
                      'collection of datasets that includes this site (for example, '
                      "the labels 'site1', 'site2' may appear in other datasets thus "
                      'rendering them indistinguishable).'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'AIDA_site_1; AIDA_site_2'}]} })
    sample_collection_relative_time_point: Optional[str] = Field(default=None, title="Sample Collection Relative Time Point", description="""Time point when the sample was collected. This field is only needed if multiple samples from the same subject are available and collected at different time points. Sample collection dates (e.g. 23/09/22) cannot be used due to patient data protection, only relative time points should be used here (e.g. day3).""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_relative_time_point',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Explains variability in the data between samples from the same '
                      'subject.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'sampleX_day1'}]} })
    tissue_free_text: Optional[str] = Field(default=None, title="Tissue Free Text", description="""The detailed anatomical location of the sample - this does not have to tie to an ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_free_text',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To help the integration team understand the anatomical location '
                      'of the sample, specifically to solve the problem when the '
                      'UBERON ontology terms are insufficiently precise.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'terminal ileum'}]} })
    tissue_type: TissueType = Field(default=..., title="Tissue Type", description="""Whether the tissue is \"tissue\", \"organoid\", or \"cell culture\".""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'tissue'}],
         'notes': ['tissue; organoid; cell culture']} })
    tissue_ontology_term_id: str = Field(default=..., title="Tissue Ontology Term ID", description="""The detailed anatomical location of the sample, please provide a specific UBERON term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'UBERON:0001828'}, {'value': 'UBERON:0000966'}],
         'notes': ['If tissue_type is "tissue" or "organoid", this must be the most '
                   'accurate child of UBERON:0001062 for anatomical entity. If '
                   'tissue_type is "cell culture" this must follow the requirements '
                   'for cell_type_ontology_term_id.\n']} })
    suspension_type: SuspensionType = Field(default=..., title="Suspension Type", description="""Specifies whether the sample contains single cells or single nuclei data.""", json_schema_extra = { "linkml_meta": {'alias': 'suspension_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'suspension_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'cell'}],
         'notes': ['This must be "cell", "nucleus", or "na".\n'
                   'This must be the correct type for the corresponding assay:\n'
                   '* 10x transcription profiling [EFO:0030080] and its children = '
                   '"cell" or "nucleus"\n'
                   '* ATAC-seq [EFO:0007045] and its children = "nucleus"\n'
                   '* BD Rhapsody Whole Transcriptome Analysis [EFO:0700003] = "cell"\n'
                   '* BD Rhapsody Targeted mRNA [EFO:0700004] = "cell"\n'
                   '* CEL-seq2 [EFO:0010010] = "cell" or "nucleus"\n'
                   '* CITE-seq [EFO:0009294] and its children = "cell"\n'
                   '* DroNc-seq [EFO:0008720] = "nucleus"\n'
                   '* Drop-seq [EFO:0008722] = "cell" or "nucleus"\n'
                   '* GEXSCOPE technology [EFO:0700011] = "cell" or "nucleus"\n'
                   '* inDrop [EFO:0008780] = "cell" or "nucleus"\n']} })
    sampled_site_condition: SampledSiteCondition = Field(default=..., title="Sampled Site Condition", description="""Whether the site is considered healthy, diseased or adjacent to disease.""", json_schema_extra = { "linkml_meta": {'alias': 'sampled_site_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'healthy'}],
         'notes': ['healthy; diseased; adjacent']} })
    sample_preservation_method: SamplePreservationMethod = Field(default=..., title="Sample Preservation Method", description="""Indicating if tissue was frozen, or not, at any point before library preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_preservation_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'fresh'}],
         'notes': ['ambient temperature; cut slide; fresh; frozen at -70C; frozen at '
                   '-80C; frozen at -150C; frozen in liquid nitrogen; frozen in vapor '
                   'phase; paraffin block; RNAlater at 4C; RNAlater at 25C; RNAlater '
                   'at -20C; other']} })
    sample_source: SampleSource = Field(default=..., title="Sample Source", description="""The study subgroup that the participant belongs to, indicating whether the participant was a surgical donor, a postmortem donor, or an organ donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_source',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'surgical donor'}],
         'notes': ['surgical donor; postmortem donor; living organ donor']} })
    tissue_ontology_term: Optional[str] = Field(default=None, title="Tissue Ontology Term", description="""Deprecated placeholder for tissue ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term',
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })


class GutDataset(Dataset):
    """
    Dataset with Gut BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/gut'})

    ambient_count_correction: str = Field(default=..., title="Ambient Count Correction", description="""Method used to correct ambient RNA contamination in single-cell data.""", json_schema_extra = { "linkml_meta": {'alias': 'ambient_count_correction',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['AdiposeDataset', 'GutDataset'],
         'examples': [{'value': 'none'}, {'value': 'soupx'}, {'value': 'cellbender'}]} })
    doublet_detection: str = Field(default=..., title="Doublet Detection", description="""Was doublet detection software used during CELLxGENE processing? If so, which software?""", json_schema_extra = { "linkml_meta": {'alias': 'doublet_detection',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['AdiposeDataset', 'GutDataset'],
         'examples': [{'value': 'none'},
                      {'value': 'doublet_finder'},
                      {'value': 'manual'}]} })
    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cellranger_8.0.0'}]} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term Id", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'}},
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
                   'child.\n'
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
    assay_ontology_term: Optional[str] = Field(default=None, title="Assay Ontology Term", description="""Deprecated placeholder for assay ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term',
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor.  The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'batch_condition'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample.  Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.
""", json_schema_extra = { "linkml_meta": {'alias': 'comments',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    consortia: Optional[str] = Field(default=None, title="Consortia", description="""Deprecated placeholder for consortia information.""", json_schema_extra = { "linkml_meta": {'alias': 'consortia', 'domain_of': ['Dataset'], 'is_a': 'deprecated_slot'} })
    contact_email: str = Field(default=..., title="Contact Email", description="""Contact name and email of the submitting person""", json_schema_extra = { "linkml_meta": {'alias': 'contact_email', 'domain_of': ['Dataset']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'default_embedding'}},
         'domain_of': ['Dataset']} })
    description: str = Field(default=..., title="Description", description="""Short description of the dataset""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40
""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    intron_inclusion: Optional[YesNoEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}, {'value': 'no'}]} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol;  or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.
""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    publication_doi: Optional[str] = Field(default=None, title="Publication DOI", description="""The publication digital object identifier (doi) for the protocol. If no pre-print nor publication exists, please write 'not applicable'.
""", json_schema_extra = { "linkml_meta": {'alias': 'publication_doi',
         'domain_of': ['Dataset'],
         'examples': [{'value': '10.1016/j.cell.2016.07.054'}]} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCm37'}, {'value': 'GRCh37'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols/ontologies/efo/terms?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    study_pi: list[str] = Field(default=..., title="Study Pi", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last '
                                      'Name,MiddleInitial, FirstName format',
                       'value': '["Teichmann,Sarah,A."]'}]} })
    title: Optional[str] = Field(default=None, title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection.  It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata  such as a different assay to disambiguate it from other datasets in the collection.
""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'title'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': "Cells of the adult human heart collection is 'All — "
                                "Cells of the adult human heart'"}],
         'is_a': 'deprecated_slot'} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })


class GutSample(Sample):
    """
    Sample with Gut BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/gut'})

    radial_tissue_term: RadialTissueTerm = Field(default=..., title="Radial Tissue Term", description="""Radial compartment/location of the tissue sample.""", json_schema_extra = { "linkml_meta": {'alias': 'radial_tissue_term', 'domain_of': ['GutSample']} })
    dissociation_protocol: str = Field(default=..., title="Dissociation Protocol", description="""Dissociation chemicals used during sample preparation""", json_schema_extra = { "linkml_meta": {'alias': 'dissociation_protocol',
         'domain_of': ['AdiposeSample', 'GutSample'],
         'notes': ['trypsin; trypLE; collagenase']} })
    sample_id: str = Field(default=..., title="Sample ID", description="""Identification number of the sample. This is the fundamental unit of sampling the tissue (the specimen taken from the subject), which can be the same as the 'subject_ID', but is often different if multiple samples are taken from the same subject. Note: this is NOT a unit of multiplexing of donor samples, which should be stored in \"library\".""", json_schema_extra = { "linkml_meta": {'alias': 'sample_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'SC24; SC25; SC28'}]} })
    donor_id: str = Field(default=..., title="Donor ID", description="""This must be free-text that identifies a unique individual that data were derived from.""", json_schema_extra = { "linkml_meta": {'alias': 'donor_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'donor_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of biological variation of the data. It is '
                      'strongly recommended that this identifier be designed so that '
                      'it is unique to: a given individual within the collection of '
                      'datasets that includes this dataset, and a given individual '
                      'across all collections in CELLxGENE Discover. It is strongly '
                      'recommended that "pooled" be used for observations from a '
                      'sample of multiple individuals that were not confidently '
                      'assigned to a single individual through demultiplexing. It is '
                      'strongly recommended that "unknown" ONLY be used for '
                      'observations in a dataset when it is not known which '
                      'observations are from the same individual.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1; MM_donor_1; LR_donor_2'}]} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })
    author_batch_notes: Optional[str] = Field(default=None, title="Author Batch Notes", description="""Encoding of author knowledge on any further information related to likely batch effects.""", json_schema_extra = { "linkml_meta": {'alias': 'author_batch_notes',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Space for author intuition of batch effects in their dataset'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'Batch run by different personnel on different days'}]} })
    age_range: Optional[str] = Field(default=None, title="Age Range", description="""Deprecated placeholder for age range metadata.""", json_schema_extra = { "linkml_meta": {'alias': 'age_range', 'domain_of': ['Sample'], 'is_a': 'deprecated_slot'} })
    cell_number_loaded: Optional[int] = Field(default=None, title="Cell Number Loaded", description="""Estimated number of cells loaded for library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_number_loaded',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Can explain the number of doublets found in samples'],
         'domain_of': ['Sample'],
         'examples': [{'value': '5000; 4000'}]} })
    cell_viability_percentage: Optional[Union[Decimal, str]] = Field(default=None, title="Cell Viability Percentage", description="""If measured, per sample cell viability before library preparation (as a percentage).""", json_schema_extra = { "linkml_meta": {'alias': 'cell_viability_percentage',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'any_of': [{'range': 'decimal'}, {'range': 'string'}],
         'comments': ['Is a measure of sample quality that could be used to explain '
                      'outlier samples'],
         'domain_of': ['Sample'],
         'examples': [{'value': '88; 95; 93.5'}, {'value': 'unknown'}]} })
    cell_enrichment: str = Field(default=..., title="Cell Enrichment", description="""Specifies the cell types targeted for enrichment or depletion beyond the selection of live cells.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_enrichment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'CL:0000057+'}],
         'notes': ['This must be a Cell Ontology (CL) term '
                   '(http://www.ebi.ac.uk/ols4/ontologies/cl). For cells that are '
                   "enriched, list the CL code followed by a '+'. For cells that were "
                   "depleted, list the CL code followed by a '-'. If no enrichment or "
                   "depletion occurred, please use 'na' (not applicable)"]} })
    development_stage_ontology_term_id: DevelopmentStage = Field(default=..., title="Development Stage Ontology Term ID", description="""Age of the subject.""", json_schema_extra = { "linkml_meta": {'alias': 'development_stage_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg',
                                 'value': 'development_stage_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'HsapDv:0000237'}],
         'notes': ['If organism_ontolology_term_id is "NCBITaxon:9606" for Homo '
                   'sapiens, this should be an HsapDv term. If '
                   'organism_ontolology_term_id is "NCBITaxon:10090" for Mus musculus, '
                   'this should be an MmusDv term. Refer to broader age bracket terms '
                   'as needed.']} })
    disease_ontology_term_id: str = Field(default=..., title="Disease Ontology Term ID", description="""Disease, if expected to impact the sample.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'disease_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'MONDO:0005385'}, {'value': 'PATO:0000461'}],
         'notes': ['This must be a MONDO term or "PATO:0000461" for normal or '
                   'healthy.\n'
                   '\n'
                   'Requirements for data contributors adhering to GDPR or like '
                   'standards: In the case of disease, HCA requests that you submit a '
                   'higher order ontology term - this is especially important in the '
                   'case of rare disease.\n']} })
    disease_ontology_term: Optional[str] = Field(default=None, title="Disease Ontology Term", description="""Deprecated placeholder for disease ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term',
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })
    institute: str = Field(default=..., title="Institute", description="""Institution where the samples were processed.""", json_schema_extra = { "linkml_meta": {'alias': 'institute',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To be able to link to other studies from the same institution '
                      'as sometimes samples from different labs in the same institute '
                      'are processed via similar core facilities. Thus batch effects '
                      'may be smaller for datasets from the same institute even if '
                      'other factors differ.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'EMBL-EBI; Genome Institute of Singapore'}]} })
    is_primary_data: Optional[str] = Field(default=None, title="Is Primary Data", description="""Deprecated placeholder indicating whether sample represents primary data.""", json_schema_extra = { "linkml_meta": {'alias': 'is_primary_data', 'domain_of': ['Sample'], 'is_a': 'deprecated_slot'} })
    library_id: str = Field(default=..., title="Library ID", description="""The unique ID that is used to track libraries in the investigator's institution (should align with the publication).""", json_schema_extra = { "linkml_meta": {'alias': 'library_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['A way to track the unit of data generation. This should include '
                      'sample pooling'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'A24; NK_healthy_001'}]} })
    library_id_repository: Optional[str] = Field(default=None, title="Library ID Repository", description="""The unique ID used to track libraries from one of the following public data repositories: EGAX*, GSM*, SRX*, ERX*, DRX, HRX, CRX.""", json_schema_extra = { "linkml_meta": {'alias': 'library_id_repository',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Links a dataset back to the source from which it was ingested, '
                      'optional only if this is the same as the library_id.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'GSM1684095'}]} })
    library_preparation_batch: str = Field(default=..., title="Library Preparation Batch", description="""Indicating which samples' libraries were prepared in the same chip/plate/etc., e.g. batch1, batch2.""", json_schema_extra = { "linkml_meta": {'alias': 'library_preparation_batch',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Sample preparation is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'batch01; batch02'}]} })
    library_sequencing_run: str = Field(default=..., title="Library Sequencing Run", description="""The identifier (or accession number) that indicates which samples' libraries were sequenced in the same run.""", json_schema_extra = { "linkml_meta": {'alias': 'library_sequencing_run',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Library sequencing is a major source of batch effects'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'run1; NV0087'}]} })
    sample_collection_method: SampleCollectionMethod = Field(default=..., title="Sample Collection Method", description="""The method the sample was physically obtained from the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_method',
         'domain_of': ['Sample'],
         'notes': ['brush; scraping; biopsy; surgical resection; blood draw; body '
                   'fluid; other']} })
    sample_collection_year: Optional[str] = Field(default=None, title="Sample Collection Year", description="""Year of sample collection. Should not be detailed further (to exact month and day), to prevent identifiability.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_year',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['May explain whether a dataset was separated into smaller '
                      'batches.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '2018'}]} })
    sample_collection_site: Optional[str] = Field(default=None, title="Sample Collection Site", description="""The pseudonymised name of the site where the sample was collected.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_site',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To understand whether the collection site contributes to batch '
                      'effects. It is strongly recommended that this identifier be '
                      'designed so that it is unique to a given site within the '
                      'collection of datasets that includes this site (for example, '
                      "the labels 'site1', 'site2' may appear in other datasets thus "
                      'rendering them indistinguishable).'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'AIDA_site_1; AIDA_site_2'}]} })
    sample_collection_relative_time_point: Optional[str] = Field(default=None, title="Sample Collection Relative Time Point", description="""Time point when the sample was collected. This field is only needed if multiple samples from the same subject are available and collected at different time points. Sample collection dates (e.g. 23/09/22) cannot be used due to patient data protection, only relative time points should be used here (e.g. day3).""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_relative_time_point',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Explains variability in the data between samples from the same '
                      'subject.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'sampleX_day1'}]} })
    tissue_free_text: Optional[str] = Field(default=None, title="Tissue Free Text", description="""The detailed anatomical location of the sample - this does not have to tie to an ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_free_text',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['To help the integration team understand the anatomical location '
                      'of the sample, specifically to solve the problem when the '
                      'UBERON ontology terms are insufficiently precise.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'terminal ileum'}]} })
    tissue_type: TissueType = Field(default=..., title="Tissue Type", description="""Whether the tissue is \"tissue\", \"organoid\", or \"cell culture\".""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'tissue'}],
         'notes': ['tissue; organoid; cell culture']} })
    tissue_ontology_term_id: str = Field(default=..., title="Tissue Ontology Term ID", description="""The detailed anatomical location of the sample, please provide a specific UBERON term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'UBERON:0001828'}, {'value': 'UBERON:0000966'}],
         'notes': ['If tissue_type is "tissue" or "organoid", this must be the most '
                   'accurate child of UBERON:0001062 for anatomical entity. If '
                   'tissue_type is "cell culture" this must follow the requirements '
                   'for cell_type_ontology_term_id.\n']} })
    suspension_type: SuspensionType = Field(default=..., title="Suspension Type", description="""Specifies whether the sample contains single cells or single nuclei data.""", json_schema_extra = { "linkml_meta": {'alias': 'suspension_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'suspension_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'cell'}],
         'notes': ['This must be "cell", "nucleus", or "na".\n'
                   'This must be the correct type for the corresponding assay:\n'
                   '* 10x transcription profiling [EFO:0030080] and its children = '
                   '"cell" or "nucleus"\n'
                   '* ATAC-seq [EFO:0007045] and its children = "nucleus"\n'
                   '* BD Rhapsody Whole Transcriptome Analysis [EFO:0700003] = "cell"\n'
                   '* BD Rhapsody Targeted mRNA [EFO:0700004] = "cell"\n'
                   '* CEL-seq2 [EFO:0010010] = "cell" or "nucleus"\n'
                   '* CITE-seq [EFO:0009294] and its children = "cell"\n'
                   '* DroNc-seq [EFO:0008720] = "nucleus"\n'
                   '* Drop-seq [EFO:0008722] = "cell" or "nucleus"\n'
                   '* GEXSCOPE technology [EFO:0700011] = "cell" or "nucleus"\n'
                   '* inDrop [EFO:0008780] = "cell" or "nucleus"\n']} })
    sampled_site_condition: SampledSiteCondition = Field(default=..., title="Sampled Site Condition", description="""Whether the site is considered healthy, diseased or adjacent to disease.""", json_schema_extra = { "linkml_meta": {'alias': 'sampled_site_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'healthy'}],
         'notes': ['healthy; diseased; adjacent']} })
    sample_preservation_method: SamplePreservationMethod = Field(default=..., title="Sample Preservation Method", description="""Indicating if tissue was frozen, or not, at any point before library preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_preservation_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'fresh'}],
         'notes': ['ambient temperature; cut slide; fresh; frozen at -70C; frozen at '
                   '-80C; frozen at -150C; frozen in liquid nitrogen; frozen in vapor '
                   'phase; paraffin block; RNAlater at 4C; RNAlater at 25C; RNAlater '
                   'at -20C; other']} })
    sample_source: SampleSource = Field(default=..., title="Sample Source", description="""The study subgroup that the participant belongs to, indicating whether the participant was a surgical donor, a postmortem donor, or an organ donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_source',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Sample'],
         'examples': [{'value': 'surgical donor'}],
         'notes': ['surgical donor; postmortem donor; living organ donor']} })
    tissue_ontology_term: Optional[str] = Field(default=None, title="Tissue Ontology Term", description="""Deprecated placeholder for tissue ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term',
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })


class Cell(ConfiguredBaseModel):
    """
    A single cell derived from a sample
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/cell'})

    pass


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Dataset.model_rebuild()
AdiposeDataset.model_rebuild()
Donor.model_rebuild()
Sample.model_rebuild()
AdiposeSample.model_rebuild()
GutDataset.model_rebuild()
GutSample.model_rebuild()
Cell.model_rebuild()

