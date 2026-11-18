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
version = "0.3.1"  # x-release-please-version


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
                 'bionetwork/genetic-diversity',
                 'bionetwork/gut',
                 'bionetwork/musculoskeletal',
                 'donor',
                 'sample',
                 'cell',
                 'tier_2_slots'],
     'license': 'MIT',
     'name': 'hca-validation-core',
     'prefixes': {'hca': {'prefix_prefix': 'hca',
                          'prefix_reference': 'https://github.com/clevercanary/hca-validation-tools/schema/'},
                  'linkml': {'prefix_prefix': 'linkml',
                             'prefix_reference': 'https://w3id.org/linkml/'}},
     'source_file': 'src/hca_metadata_schema/core.yaml',
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
    surgical_resection = "surgical resection"
    blood_draw = "blood draw"
    body_fluid = "body fluid"
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
    surgical_donor = "surgical donor"
    postmortem_donor = "postmortem donor"
    living_organ_donor = "living organ donor"


class MannerOfDeath(str, Enum):
    number_1 = "1"
    number_2 = "2"
    number_3 = "3"
    number_4 = "4"
    number_0 = "0"
    unknown = "unknown"
    not_applicable = "not applicable"


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
    HsapDvCOLON0000244 = "HsapDv:0000244"
    HsapDvCOLON0000245 = "HsapDv:0000245"
    MmusDvCOLON0000001 = "MmusDv:0000001"
    MmusDvCOLON0000002 = "MmusDv:0000002"
    unknown = "unknown"


class Organism(str, Enum):
    NCBITaxonCOLON9606 = "NCBITaxon:9606"
    NCBITaxonCOLON10090 = "NCBITaxon:10090"


class BioNetwork(str, Enum):
    """
    HCA biological network keys, as used by the HCA Data Portal and the Atlas Tracker. Bionetwork subclasses name theirs in a `bioNetwork` class annotation.
    """
    adipose = "adipose"
    breast = "breast"
    development = "development"
    eye = "eye"
    genetic_diversity = "genetic-diversity"
    gut = "gut"
    heart = "heart"
    immune = "immune"
    kidney = "kidney"
    liver = "liver"
    lung = "lung"
    musculoskeletal = "musculoskeletal"
    nervous_system = "nervous-system"
    oral_and_craniofacial = "oral-and-craniofacial"
    organoid = "organoid"
    pancreas = "pancreas"
    reproduction = "reproduction"
    skin = "skin"



class Dataset(ConfiguredBaseModel):
    """
    A collection of data from a single experiment or study in the Human Cell Atlas
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/dataset',
         'slot_usage': {'dataset_id': {'identifier': True,
                                       'name': 'dataset_id',
                                       'range': 'string'}}})

    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cell ranger 3.0.1'},
                      {'value': 'kallisto bustools'},
                      {'value': 'GSNAP'}]} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term ID", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major source of batch effect and dataset filtering criterion.'],
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
                   '- Visium Spatial Gene Expression "EFO:0010961"']} })
    assay_ontology_term: Optional[str] = Field(default=None, title="Assay Ontology Term", description="""Deprecated placeholder for assay ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor. The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'batch_condition'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample. Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.""", json_schema_extra = { "linkml_meta": {'alias': 'comments',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    consortia: Optional[str] = Field(default=None, title="Consortia", description="""Deprecated placeholder for consortia information.""", json_schema_extra = { "linkml_meta": {'alias': 'consortia',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    contact_email: str = Field(default=..., title="Contact Email", description="""Contact name and email of the submitting person""", json_schema_extra = { "linkml_meta": {'alias': 'contact_email',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'default_embedding'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    description: str = Field(default=..., title="Description", description="""Short description of the dataset""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'v110'}, {'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    intron_inclusion: Optional[YesNoEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects the number of reads per cell called in a sample.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}, {'value': 'no'}]} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol; or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    publication_doi: Optional[str] = Field(default=None, title="Publication DOI", description="""The publication digital object identifier (doi) for the protocol. If no pre-print nor publication exists, please write 'not applicable'.""", json_schema_extra = { "linkml_meta": {'alias': 'publication_doi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'examples': [{'value': '10.1016/j.cell.2016.07.054'}]} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCh38'}, {'value': 'GRCh37'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols4/ontologies/efo/classes?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    study_pi: list[str] = Field(default=..., title="Study PI", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last name,First '
                                      'name,Middle initial format',
                       'value': 'Teichmann,Sarah,A.'}]} })
    title: str = Field(default=..., title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection. It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata such as a different assay to disambiguate it from other datasets in the collection.""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'title'},
                         'entrySheetRequired': {'tag': 'entrySheetRequired',
                                                'value': False},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Distinguishes this dataset from others in the same collection.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'Cells of the adult human heart collection is "All — '
                                'Cells of the adult human heart"'}]} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })


class AdiposeDataset(Dataset):
    """
    Dataset with Adipose BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'bioNetwork': {'tag': 'bioNetwork', 'value': 'adipose'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/adipose'})

    ambient_count_correction: str = Field(default=..., title="Ambient Count Correction", description="""Software used to correct ambient RNA counts, or 'none'.""", json_schema_extra = { "linkml_meta": {'alias': 'ambient_count_correction',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeDataset', 'GutDataset', 'MusculoskeletalDataset'],
         'examples': [{'value': 'none'}, {'value': 'soupx'}, {'value': 'cellbender'}]} })
    doublet_detection: str = Field(default=..., title="Doublet Detection", description="""Was doublet detection software used during CELLxGENE processing? If so, which software?""", json_schema_extra = { "linkml_meta": {'alias': 'doublet_detection',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeDataset', 'GutDataset', 'MusculoskeletalDataset'],
         'examples': [{'value': 'none'},
                      {'value': 'doublet_finder'},
                      {'value': 'manual'}]} })
    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cell ranger 3.0.1'},
                      {'value': 'kallisto bustools'},
                      {'value': 'GSNAP'}]} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term ID", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major source of batch effect and dataset filtering criterion.'],
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
                   '- Visium Spatial Gene Expression "EFO:0010961"']} })
    assay_ontology_term: Optional[str] = Field(default=None, title="Assay Ontology Term", description="""Deprecated placeholder for assay ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor. The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'batch_condition'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample. Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.""", json_schema_extra = { "linkml_meta": {'alias': 'comments',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    consortia: Optional[str] = Field(default=None, title="Consortia", description="""Deprecated placeholder for consortia information.""", json_schema_extra = { "linkml_meta": {'alias': 'consortia',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    contact_email: str = Field(default=..., title="Contact Email", description="""Contact name and email of the submitting person""", json_schema_extra = { "linkml_meta": {'alias': 'contact_email',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'default_embedding'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    description: str = Field(default=..., title="Description", description="""Short description of the dataset""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'v110'}, {'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    intron_inclusion: Optional[YesNoEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects the number of reads per cell called in a sample.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}, {'value': 'no'}]} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol; or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    publication_doi: Optional[str] = Field(default=None, title="Publication DOI", description="""The publication digital object identifier (doi) for the protocol. If no pre-print nor publication exists, please write 'not applicable'.""", json_schema_extra = { "linkml_meta": {'alias': 'publication_doi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'examples': [{'value': '10.1016/j.cell.2016.07.054'}]} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCh38'}, {'value': 'GRCh37'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols4/ontologies/efo/classes?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    study_pi: list[str] = Field(default=..., title="Study PI", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last name,First '
                                      'name,Middle initial format',
                       'value': 'Teichmann,Sarah,A.'}]} })
    title: str = Field(default=..., title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection. It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata such as a different assay to disambiguate it from other datasets in the collection.""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'title'},
                         'entrySheetRequired': {'tag': 'entrySheetRequired',
                                                'value': False},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Distinguishes this dataset from others in the same collection.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'Cells of the adult human heart collection is "All — '
                                'Cells of the adult human heart"'}]} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })


class GeneticDiversityDonorTier2(ConfiguredBaseModel):
    """
    Genetic Diversity BioNetwork Tier 2 donor metadata, collected under managed access.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'baseClass': {'tag': 'baseClass', 'value': 'Donor'},
                         'bioNetwork': {'tag': 'bioNetwork',
                                        'value': 'genetic-diversity'},
                         'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/genetic-diversity',
         'mixin': True})

    age_value: Optional[int] = Field(default=None, title="Age Value", description="""Age of donor at the time of sample collection. Specify the age unit (week, month, year) in age_unit.""", json_schema_extra = { "linkml_meta": {'alias': 'age_value',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Age can impact cellular and molecular phenotypes.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '20'}, {'value': '32'}, {'value': '56'}]} })
    age_unit: Optional[str] = Field(default=None, title="Age Unit", description="""Age unit (week, month, year) for the age_value.""", json_schema_extra = { "linkml_meta": {'alias': 'age_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Age can impact cellular and molecular phenotypes.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })
    bmi: Optional[Decimal] = Field(default=None, title="BMI", description="""Body mass index of the donor at the time of collection.""", json_schema_extra = { "linkml_meta": {'alias': 'bmi',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['May serve as a covariate for analysis of human diversity. If '
                      'height or weight is not provided but BMI is, fill here.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '36.4'}, {'value': '19.2'}, {'value': '27'}]} })
    height: Optional[int] = Field(default=None, title="Height", description="""Height of donor in cm at the time of collection.""", json_schema_extra = { "linkml_meta": {'alias': 'height',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Highly heritable (PMID: 36224396); together with weight can '
                      'allow for computation of body-mass index, which may serve as a '
                      'covariate for analyses of human diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '160'}, {'value': '137'}, {'value': '203'}]} })
    weight: Optional[int] = Field(default=None, title="Weight", description="""Weight of donor in kilograms at the time of collection.""", json_schema_extra = { "linkml_meta": {'alias': 'weight',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Together with height can allow for computation of body-mass '
                      'index, which may serve as a covariate for analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '50'}, {'value': '80'}]} })
    genderidentity_selfreported: Optional[str] = Field(default=None, title="Gender Identity Self-Reported", description="""Donor self-reported gender identity.""", json_schema_extra = { "linkml_meta": {'alias': 'genderidentity_selfreported',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Gender identity information may be important for studies '
                      'involving hormonal treatments, etc.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Female Gender'},
                      {'value': 'Male Gender'},
                      {'value': 'Non-Binary Gender'},
                      {'value': 'Other Gender'},
                      {'value': 'Agender'},
                      {'value': 'Gender Fluid'},
                      {'value': 'Gender Identifier X'},
                      {'value': 'Genderqueer'},
                      {'value': 'Transgender'},
                      {'value': 'Two-spirit'}]} })
    ethnicity_selfreported_freetext: Optional[str] = Field(default=None, title="Ethnicity Self-Reported Free Text", description="""Donor self-reported ethnicity (or ethnicities) in free-text; can include tribe, dialect group, etc. If race information is submitted under this field, please ensure that the question(s) and response options posed to donors are included in the next metadata category (\"ethnicity_question_text\"). Separate multiple entries with a comma.""", json_schema_extra = { "linkml_meta": {'alias': 'ethnicity_selfreported_freetext',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Self-reported ethnicity information can encompass language, '
                      'religion, tribe, and cultural factors, beyond genetic '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2']} })
    ethnicity_question_text: Optional[str] = Field(default=None, title="Ethnicity Question Text", description="""Question and response options posed to donors for collecting metadata on donor self-reported ethnicity and / or tribe and / or dialect group and / or race etc.""", json_schema_extra = { "linkml_meta": {'alias': 'ethnicity_question_text',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Provides context on the method for collecting self-reported '
                      'ethnicity, tribe, dialect group, or race information. '
                      'Self-reported ethnicity information can encompass language, '
                      'religion, tribe, and cultural factors, beyond genetic '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '"What is your ethnicity?"'},
                      {'value': '"Are you Hispanic/Latino?"'},
                      {'value': 'Example from All of Us "Which categories describe '
                                'you? Select all that apply. Note You may select more '
                                'than one group. American Indian or Alaska Native (for '
                                'example, Aztec, Blackfeet Tribe, Mayan, Navajo '
                                'Nation, Native Village of Barrow (Utqiagvik) Inupiat '
                                'Traditional Government, Nome Eskimo Community, etc.)* '
                                'Asian (for example, Asian Indian, Chinese, Filipino, '
                                'Japanese, Korean, Vietnamese, etc.)* Black, African '
                                'American, or African (for example, African American, '
                                'Ethiopian, Haitian, Jamaican, Nigerian, Somali, '
                                'etc.)* Hispanic, Latino, or Spanish (for example, '
                                'Columbian, Cuban, Dominican, Mexican or Mexican '
                                'American, Puerto Rican, Salvadoran, etc.)* Middle '
                                'Eastern or North African (for example, Algerian, '
                                'Egyptian, Iranian, Lebanese, Moroccan, Syrian, etc.)* '
                                'Native Hawaiian or other Pacific Islander (for '
                                'example, Chamorro, Fijian, Marshallese, Native '
                                'Hawaiian, Tongan, etc.)* White (for example, English, '
                                'European, French, German, Irish, Italian, Polish, '
                                'etc.)* None of these fully describe me (optional free '
                                'text answer) Prefer not to answer" not collected, not '
                                'available'}]} })
    language_donor_primary_language: Optional[str] = Field(default=None, title="Language Donor Primary Language", description="""Primary language(s), spoken by donor. Can include dialects (for example, Hokkien).""", json_schema_extra = { "linkml_meta": {'alias': 'language_donor_primary_language',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Primary language(s) may contain information relevant to '
                      "ancestry, as well as a donor's environmental and cultural "
                      'context.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Mandarin Chinese'},
                      {'value': 'Hokkien'},
                      {'value': 'Bahasa Melayu'},
                      {'value': 'Tamil'},
                      {'value': 'Hausa'},
                      {'value': 'Yoruba'},
                      {'value': 'Swahili'}]} })
    geography_currentresidence_location_country_state: Optional[str] = Field(default=None, title="Geography Current Residence Location Country State", description="""Country and state of donor's current residence at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_location_country_state',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a coarser level (country '
                      'and state).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'United Kingdom'},
                      {'value': 'Massachusetts USA'},
                      {'value': 'New South Wales Australia'},
                      {'value': 'Bauchi State'},
                      {'value': 'Nigeria'}]} })
    geography_currentresidence_location_granular: Optional[str] = Field(default=None, title="Geography Current Residence Location Granular", description="""Nearest city, town, or village to location of donor's current residence at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_location_granular',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a more granular level '
                      '(city / town / village).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'Cambridge'},
                      {'value': 'Boston'},
                      {'value': 'Kingston'}]} })
    medication: Optional[str] = Field(default=None, title="Medication", description="""List of prescription medication consumed by the donor at time of sample collection. Should be an NCIT ontology term""", json_schema_extra = { "linkml_meta": {'alias': 'medication',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Medication consumption may be a covariate / exclusion criterion '
                      'in analyses of human diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'atorvastatin'},
                      {'value': 'brevicon'},
                      {'value': 'chlorthalidone'}],
         'notes': ['[NCIT ontology '
                   'term](https://www.ebi.ac.uk/ols4/ontologies/ncit/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FNCIT_C1908?lang=en)']} })
    diet_meat_consumption: Optional[str] = Field(default=None, title="Diet Meat Consumption", description="""Dietary patterns of donor – meat (chicken, seafood, fish, pork, lamb, beef, etc.) consumption versus meat-free diet – at time of sample collection. Fill yes if donor consumes meat or no if donor does not consumes meat.""", json_schema_extra = { "linkml_meta": {'alias': 'diet_meat_consumption',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Diet can impact cellular and molecular phenotypes.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'yes'}, {'value': 'no'}],
         'notes': ['yes; no']} })
    smoking_status: Optional[str] = Field(default=None, title="Smoking Status", description="""If the donor smokes/smoked or not.""", json_schema_extra = { "linkml_meta": {'alias': 'smoking_status',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Smoking may impact cellular and molecular phenotypes, and can '
                      'serve as a covariate for human diversity analyses.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'active'}, {'value': 'former'}, {'value': 'never'}],
         'notes': ['active; former; never']} })
    geography_collectionsite_latitude_longitude: Optional[str] = Field(default=None, title="Geography Collectionsite Latitude Longitude", description="""Latitude and longitude GPS coordinates of collection site in decimal degrees.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_collectionsite_latitude_longitude',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Contains information relevant for geographical diversity of '
                      'donors; possible proxy for environmental exposures.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '1.3, 103.8'}, {'value': 'not_sharable'}]} })
    geography_currentresidence_duration: Optional[int] = Field(default=None, title="Geography Currentresidence Duration", description="""Duration of residence, in years, rounded up to the nearest whole number, at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_duration',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Indication of duration of environmental exposure relating to '
                      'current residence.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '20'}, {'value': '37'}, {'value': '45'}]} })
    geography_currentresidence_urbanrural: Optional[str] = Field(default=None, title="Geography Currentresidence Urban Rural", description="""Urban, suburban, or rural descriptor of current residence.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_urbanrural',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Contains information on environmental exposure relating to '
                      'current residence'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'urban'}, {'value': 'suburban'}, {'value': 'rural'}],
         'notes': ['urban; suburban; rural']} })
    geography_placeofbirth_location_country_state: Optional[str] = Field(default=None, title="Geography Place of Birth Location Country State", description="""Country and state of place of birth.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_location_country_state',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a coarser level (country '
                      'and state).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'United Kingdom'},
                      {'value': 'Massachusetts USA'},
                      {'value': 'New South Wales Australia'},
                      {'value': 'Bauchi State'},
                      {'value': 'Nigeria'}]} })
    geography_placeofbirth_location_granular: Optional[str] = Field(default=None, title="Geography Place of Birth Location Granular", description="""Nearest city, town, or village to location of place of birth.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_location_granular',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a more granular level '
                      '(city / town / village).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'Cambridge'},
                      {'value': 'Boston'},
                      {'value': 'Kingston'}]} })
    geography_placeofbirth_duration: Optional[int] = Field(default=None, title="Geography Place of Birth Duration", description="""Duration of residence, in years, rounded up to the nearest whole number.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_duration',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Indication of duration of environmental exposure relating to '
                      'place of birth.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '20'}, {'value': '37'}, {'value': '45'}]} })
    geography_placeofbirth_urbanrural: Optional[str] = Field(default=None, title="Geography Place of Birth Urban Rural", description="""Urban, suburban, or rural descriptor of place of birth.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_urbanrural',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Contains information on environmental exposure relating to '
                      'place of birth'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'urban'}, {'value': 'suburban'}, {'value': 'rural'}],
         'notes': ['urban; suburban; rural']} })
    ethnicity_parents_selfreported_freetext: Optional[str] = Field(default=None, title="Ethnicity Parents Self-Reported Freetext", description="""Donor's parents' self-reported ethnicity (or ethnicities) in free-text; can include tribe, dialect group, etc. Separate multiple entries with a comma.""", json_schema_extra = { "linkml_meta": {'alias': 'ethnicity_parents_selfreported_freetext',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Self-reported ethnicity information can encompass language, '
                      'religion, tribe, and cultural factors, beyond genetic '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singaporean Chinese'},
                      {'value': 'Singaporean Malay'},
                      {'value': 'Singaporean Indian'},
                      {'value': 'Haitian'},
                      {'value': 'Nigerian Hausa'},
                      {'value': 'Ghana Hausa'},
                      {'value': 'Benin Kanuri'},
                      {'value': 'Nigerian Kanuri'},
                      {'value': 'Igbo'},
                      {'value': 'Luo'},
                      {'value': 'Herero'},
                      {'value': 'Garifuna'},
                      {'value': 'Kalinago'}]} })
    language_mother_father_tongue: Optional[str] = Field(default=None, title="Language Mother Father Tongue", description="""Ancestral language(s), spoken by parents (\"mother tongue\" and / or \"father tongue\") and / or grandparents. Can include dialects (for example, Hokkien).""", json_schema_extra = { "linkml_meta": {'alias': 'language_mother_father_tongue',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Mother and father tongues may contain information relevant to '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Mandarin Chinese'},
                      {'value': 'Hokkien'},
                      {'value': 'Bahasa Melayu'},
                      {'value': 'Tamil'},
                      {'value': 'Hausa'},
                      {'value': 'Yoruba'},
                      {'value': 'Swahili'}]} })
    menarche_age: Optional[int] = Field(default=None, title="Menarche Age", description="""Age at menarche, rounded to nearest whole number.""", json_schema_extra = { "linkml_meta": {'alias': 'menarche_age',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Age at menarche may be a covariate in analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '13'}, {'value': '12'}, {'value': '16'}]} })
    reproductive_menopause: Optional[str] = Field(default=None, title="Reproductive Menopause", description="""Menopausal status of donor at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'reproductive_menopause',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Menopausal status may be a covariate in analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'pre-menopausal'},
                      {'value': 'peri-menopausal'},
                      {'value': 'post-menopausal'},
                      {'value': 'post-menopausal (induced)'},
                      {'value': 'not applicable'}],
         'notes': ['pre-menopausal; peri-menopausal; post-menopausal; post-menopausal '
                   '(induced); not applicable']} })
    reproductive_number_children: Optional[int] = Field(default=None, title="Reproductive Number Children", description="""Number of children (full-term pregnancies) the donor has given birth to at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'reproductive_number_children',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Number of children (full-term pregnancies) may be a covariate '
                      'in analyses of human diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '0'}, {'value': '2'}, {'value': '3'}]} })
    reproductive_number_pregnancies: Optional[int] = Field(default=None, title="Reproductive Number Pregnancies", description="""Number of pregnancies the donor has had at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'reproductive_number_pregnancies',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Number of pregnancies may be a covariate in analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '2'}, {'value': '3'}, {'value': '5'}]} })


class GutDataset(Dataset):
    """
    Dataset with Gut BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'bioNetwork': {'tag': 'bioNetwork', 'value': 'gut'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/gut'})

    ambient_count_correction: str = Field(default=..., title="Ambient Count Correction", description="""Software used to correct ambient RNA counts, or 'none'.""", json_schema_extra = { "linkml_meta": {'alias': 'ambient_count_correction',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeDataset', 'GutDataset', 'MusculoskeletalDataset'],
         'examples': [{'value': 'none'}, {'value': 'soupx'}, {'value': 'cellbender'}]} })
    doublet_detection: str = Field(default=..., title="Doublet Detection", description="""Was doublet detection software used during CELLxGENE processing? If so, which software?""", json_schema_extra = { "linkml_meta": {'alias': 'doublet_detection',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeDataset', 'GutDataset', 'MusculoskeletalDataset'],
         'examples': [{'value': 'none'},
                      {'value': 'doublet_finder'},
                      {'value': 'manual'}]} })
    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cell ranger 3.0.1'},
                      {'value': 'kallisto bustools'},
                      {'value': 'GSNAP'}]} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term ID", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major source of batch effect and dataset filtering criterion.'],
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
                   '- Visium Spatial Gene Expression "EFO:0010961"']} })
    assay_ontology_term: Optional[str] = Field(default=None, title="Assay Ontology Term", description="""Deprecated placeholder for assay ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor. The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'batch_condition'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample. Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.""", json_schema_extra = { "linkml_meta": {'alias': 'comments',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    consortia: Optional[str] = Field(default=None, title="Consortia", description="""Deprecated placeholder for consortia information.""", json_schema_extra = { "linkml_meta": {'alias': 'consortia',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    contact_email: str = Field(default=..., title="Contact Email", description="""Contact name and email of the submitting person""", json_schema_extra = { "linkml_meta": {'alias': 'contact_email',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'default_embedding'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    description: str = Field(default=..., title="Description", description="""Short description of the dataset""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'v110'}, {'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    intron_inclusion: Optional[YesNoEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects the number of reads per cell called in a sample.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}, {'value': 'no'}]} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol; or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    publication_doi: Optional[str] = Field(default=None, title="Publication DOI", description="""The publication digital object identifier (doi) for the protocol. If no pre-print nor publication exists, please write 'not applicable'.""", json_schema_extra = { "linkml_meta": {'alias': 'publication_doi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'examples': [{'value': '10.1016/j.cell.2016.07.054'}]} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCh38'}, {'value': 'GRCh37'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols4/ontologies/efo/classes?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    study_pi: list[str] = Field(default=..., title="Study PI", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last name,First '
                                      'name,Middle initial format',
                       'value': 'Teichmann,Sarah,A.'}]} })
    title: str = Field(default=..., title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection. It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata such as a different assay to disambiguate it from other datasets in the collection.""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'title'},
                         'entrySheetRequired': {'tag': 'entrySheetRequired',
                                                'value': False},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Distinguishes this dataset from others in the same collection.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'Cells of the adult human heart collection is "All — '
                                'Cells of the adult human heart"'}]} })
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
         'comments': ['Fundamental unit of biological variation of the data.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1'},
                      {'value': 'MM_donor_1'},
                      {'value': 'LR_donor_2'}],
         'notes': ['It is strongly recommended that this identifier be designed so '
                   'that it is unique to: a given individual within the collection of '
                   'datasets that includes this dataset, and a given individual across '
                   'all collections in CELLxGENE Discover. It is strongly recommended '
                   'that "pooled" be used for observations from a sample of multiple '
                   'individuals that were not confidently assigned to a single '
                   'individual through demultiplexing. It is strongly recommended that '
                   '"unknown" ONLY be used for observations in a dataset when it is '
                   'not known which observations are from the same individual.']} })
    organism_ontology_term_id: Organism = Field(default=..., title="Organism Ontology Term ID", description="""The name given to the type of organism, collected in NCBITaxon:0000 format.""", json_schema_extra = { "linkml_meta": {'alias': 'organism_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'organism_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Strong biological effect that needs to be considered for batch '
                      'covariate selection.'],
         'domain_of': ['Donor'],
         'examples': [{'value': 'NCBITaxon:9606'}, {'value': 'NCBITaxon:10090'}],
         'notes': ['"NCBITaxon:9606" for Homo sapiens or "NCBITaxon:10090" for Mus '
                   'musculus.']} })
    sex_ontology_term_id: str = Field(default=..., title="Sex Ontology Term ID", description="""Reported sex of the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sex_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'sex_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Likely biological effect. Need to know if we have a balanced '
                      'dataset or if sex is collinear with the dataset.'],
         'domain_of': ['Donor'],
         'examples': [{'description': 'female', 'value': 'PATO:0000383'},
                      {'description': 'male', 'value': 'PATO:0000384'}],
         'notes': ['This must be a child of PATO:0001894 for phenotypic sex or '
                   '"unknown" if unavailable.']} })
    sex_ontology_term: Optional[str] = Field(default=None, title="Sex Ontology Term", description="""Deprecated placeholder for sex ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'sex_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Donor'],
         'is_a': 'deprecated_slot'} })
    manner_of_death: MannerOfDeath = Field(default=..., title="Manner of Death", description="""Manner of death classification based on the Hardy Scale or 'unknown' or 'not applicable':
* Category 1 = Violent and fast death - Deaths due to accident, blunt force trauma or suicide, terminal phase estimated at < 10 min.
* Category 2 = Fast death of natural causes - Sudden unexpected deaths of people who had been reasonably healthy, after a terminal phase estimated at < 1 hr (with sudden death from a myocardial infarction as a model cause of death for this category).
* Category 3 = Intermediate death - Death after a terminal phase of 1 to 24 hrs (not classifiable as 2 or 4); patients who were ill but death was unexpected.
* Category 4 = Slow death - Death after a long illness, with a terminal phase longer than 1 day (commonly cancer or chronic pulmonary disease); deaths that are not unexpected.
* Category 0 = Ventilator Case - All cases on a ventilator immediately before death.
* Unknown = The cause of death is unknown.
* Not applicable = Subject is alive.

[Please leave this field as blank for embryonic/fetal tissue.]""", json_schema_extra = { "linkml_meta": {'alias': 'manner_of_death',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Manner of death can affect cellular profiles.'],
         'domain_of': ['Donor'],
         'examples': [{'value': '1'},
                      {'value': '2'},
                      {'value': '3'},
                      {'value': '4'},
                      {'value': '0'},
                      {'value': 'unknown'},
                      {'value': 'not applicable'}]} })
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
         'comments': ['Fundamental unit of sampling of the tissue.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'SC24'}, {'value': 'SC25'}, {'value': 'SC28'}]} })
    donor_id: str = Field(default=..., title="Donor ID", description="""This must be free-text that identifies a unique individual that data were derived from.""", json_schema_extra = { "linkml_meta": {'alias': 'donor_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'donor_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of biological variation of the data.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1'},
                      {'value': 'MM_donor_1'},
                      {'value': 'LR_donor_2'}],
         'notes': ['It is strongly recommended that this identifier be designed so '
                   'that it is unique to: a given individual within the collection of '
                   'datasets that includes this dataset, and a given individual across '
                   'all collections in CELLxGENE Discover. It is strongly recommended '
                   'that "pooled" be used for observations from a sample of multiple '
                   'individuals that were not confidently assigned to a single '
                   'individual through demultiplexing. It is strongly recommended that '
                   '"unknown" ONLY be used for observations in a dataset when it is '
                   'not known which observations are from the same individual.']} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })
    author_batch_notes: Optional[str] = Field(default=None, title="Author Batch Notes", description="""Encoding of author knowledge on any further information related to likely batch effects.""", json_schema_extra = { "linkml_meta": {'alias': 'author_batch_notes',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Space for author intuition of batch effects in their dataset.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'Batch run by different personnel on different days'}]} })
    age_range: Optional[str] = Field(default=None, title="Age Range", description="""Deprecated placeholder for age range metadata.""", json_schema_extra = { "linkml_meta": {'alias': 'age_range',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })
    cell_number_loaded: Optional[int] = Field(default=None, title="Cell Number Loaded", description="""Estimated number of cells loaded for library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_number_loaded',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Can explain the number of doublets found in samples.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '5000'}, {'value': '4000'}]} })
    cell_viability_percentage: Optional[Union[Decimal, str]] = Field(default=None, title="Cell Viability Percentage", description="""If measured, per sample cell viability before library preparation (as a percentage).""", json_schema_extra = { "linkml_meta": {'alias': 'cell_viability_percentage',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'any_of': [{'range': 'decimal'}, {'range': 'string'}],
         'comments': ['Is a measure of sample quality that could be used to explain '
                      'outlier samples.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '88'},
                      {'value': '95'},
                      {'value': '93.5'},
                      {'value': 'unknown'}]} })
    cell_enrichment: str = Field(default=..., title="Cell Enrichment", description="""Specifies the cell types targeted for enrichment or depletion beyond the selection of live cells.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_enrichment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['If cell lineages were filtered, this may be a dataset exclusion '
                      'criterion.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'CL:0000057+'}, {'value': 'na'}],
         'notes': ['This must be a Cell Ontology (CL) term '
                   '(https://www.ebi.ac.uk/ols4/ontologies/cl). For cells that are '
                   'enriched, list the CL code followed by a "+". For cells that were '
                   'depleted, list the CL code followed by a "-". If no enrichment or '
                   "depletion occurred, please use 'na' (not applicable)"]} })
    development_stage_ontology_term_id: DevelopmentStage = Field(default=..., title="Development Stage Ontology Term ID", description="""Age of the subject.""", json_schema_extra = { "linkml_meta": {'alias': 'development_stage_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg',
                                 'value': 'development_stage_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Developmental stage is a key biological covariate for '
                      'interpreting cell state and comparing samples across donors.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'HsapDv:0000237'}, {'value': 'unknown'}],
         'notes': ['If organism_ontology_term_id is "NCBITaxon:9606" for *Homo '
                   'sapiens*, this should be an HsapDv term. If '
                   'organism_ontology_term_id is "NCBITaxon:10090" for *Mus musculus*, '
                   'this should be an MmusDv term.\n'
                   '\n'
                   '**Requirements for data contributors adhering to GDPR or like '
                   'standards**: HCA requests that you do not submit year-specific '
                   'terms. Refer to broader age bracket terms as needed.']} })
    disease_ontology_term_id: str = Field(default=..., title="Disease Ontology Term ID", description="""Disease, if expected to impact the sample.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'disease_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Disease has a major effect on cell state, and determines which '
                      'samples can serve as a healthy reference.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'MONDO:0005385'}, {'value': 'PATO:0000461'}],
         'notes': ['This must be a MONDO term or "PATO:0000461" for normal or '
                   'healthy.\n'
                   '\n'
                   '**Requirements for data contributors adhering to GDPR or like '
                   'standards**: In the case of disease, HCA requests that you submit '
                   'a higher order ontology term - this is especially important in the '
                   'case of rare disease.']} })
    disease_ontology_term: Optional[str] = Field(default=None, title="Disease Ontology Term", description="""Deprecated placeholder for disease ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
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
         'examples': [{'value': 'EMBL-EBI'},
                      {'value': 'Genome Institute of Singapore'}]} })
    is_primary_data: Optional[str] = Field(default=None, title="Is Primary Data", description="""This must be \"true\" if this is the canonical instance of this cellular observation and \"false\" if not. This is commonly \"false\" for meta-analyses reusing data or for secondary views of data.""", json_schema_extra = { "linkml_meta": {'alias': 'is_primary_data',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'is_primary_data'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['This helps to ensure samples are not used twice.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'true'}, {'value': 'false'}],
         'is_a': 'deprecated_slot',
         'notes': ['true; false']} })
    library_id: str = Field(default=..., title="Library ID", description="""The unique ID that is used to track libraries in the investigator's institution (should align with the publication).""", json_schema_extra = { "linkml_meta": {'alias': 'library_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['A way to track the unit of data generation. This should include '
                      'sample pooling.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'A24'}, {'value': 'NK_healthy_001'}]} })
    library_id_repository: Optional[str] = Field(default=None, title="Library ID Repository", description="""The unique ID used to track libraries from one of the following public data repositories: EGAX*, GSM*, SRX*, ERX*, DRX, HRX, CRX.""", json_schema_extra = { "linkml_meta": {'alias': 'library_id_repository',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Links a dataset back to the source from which it was ingested, '
                      'optional only if this is the same as the library_id.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'GSM1684095'}]} })
    library_preparation_batch: Optional[str] = Field(default=None, title="Library Preparation Batch", description="""Indicating which samples' libraries were prepared in the same chip/plate/etc., e.g. batch1, batch2.""", json_schema_extra = { "linkml_meta": {'alias': 'library_preparation_batch',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Sample preparation is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'batch01'}, {'value': 'batch02'}],
         'recommended': True} })
    library_sequencing_run: Optional[str] = Field(default=None, title="Library Sequencing Run", description="""The identifier (or accession number) that indicates which samples' libraries were sequenced in the same run.""", json_schema_extra = { "linkml_meta": {'alias': 'library_sequencing_run',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Library sequencing is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'run1'}, {'value': 'NV0087'}],
         'recommended': True} })
    sample_collection_method: SampleCollectionMethod = Field(default=..., title="Sample Collection Method", description="""The method the sample was physically obtained from the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'biopsy'},
                      {'value': 'brush'},
                      {'value': 'surgical resection'}]} })
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
                      'effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'AIDA_site_1'}, {'value': 'AIDA_site_2'}],
         'notes': ['It is strongly recommended that this identifier be designed so '
                   'that it is unique to a given site within the collection of '
                   "datasets that includes this site (for example, the labels 'site1', "
                   "'site2' may appear in other datasets thus rendering them "
                   'indistinguishable).']} })
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
         'comments': ['Source of batch effect & dataset exclusion criteria.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'tissue'},
                      {'value': 'organoid'},
                      {'value': 'cell culture'}]} })
    tissue_ontology_term_id: str = Field(default=..., title="Tissue Ontology Term ID", description="""The detailed anatomical location of the sample, please provide a specific UBERON term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major biological effect that needs to be assessed for '
                      'sufficient coverage in the atlas datasets.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'UBERON:0001828'}, {'value': 'UBERON:0000966'}],
         'notes': ['If tissue_type is "tissue" or "organoid", this must be the most '
                   'accurate child of UBERON:0001062 for anatomical entity. If '
                   'tissue_type is "cell culture" this must follow the requirements '
                   'for cell_type_ontology_term_id.']} })
    suspension_type: SuspensionType = Field(default=..., title="Suspension Type", description="""Specifies whether the sample contains single cells or single nuclei data.""", json_schema_extra = { "linkml_meta": {'alias': 'suspension_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'suspension_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major source of batch effect & dataset exclusion criteria.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'cell'}, {'value': 'nucleus'}, {'value': 'na'}],
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
                   '* inDrop [EFO:0008780] = "cell" or "nucleus"']} })
    sampled_site_condition: SampledSiteCondition = Field(default=..., title="Sampled Site Condition", description="""Whether the site is considered healthy, diseased or adjacent to disease.""", json_schema_extra = { "linkml_meta": {'alias': 'sampled_site_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'healthy'},
                      {'value': 'diseased'},
                      {'value': 'adjacent'}]} })
    sample_preservation_method: SamplePreservationMethod = Field(default=..., title="Sample Preservation Method", description="""Indicating if tissue was frozen, or not, at any point before library preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_preservation_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'fresh'}, {'value': 'frozen at -70C'}]} })
    sample_source: SampleSource = Field(default=..., title="Sample Source", description="""The study subgroup that the participant belongs to. This indicates whether the participant was a surgical donor (this includes patients providing blood samples or biopsies), a postmortem donor, or a living organ donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_source',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['The source of the sample (whether the sample comes from a '
                      'surgical donor, a postmortem donor or a living organ donor) can '
                      'result in different cellular profiles and hence batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'surgical donor'}, {'value': 'postmortem donor'}]} })
    tissue_ontology_term: Optional[str] = Field(default=None, title="Tissue Ontology Term", description="""Deprecated placeholder for tissue ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })


class AdiposeSample(Sample):
    """
    Sample with Adipose BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'bioNetwork': {'tag': 'bioNetwork', 'value': 'adipose'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/adipose'})

    dissociation_protocol: str = Field(default=..., title="Dissociation Protocol", description="""Dissociation chemicals used during sample preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'dissociation_protocol',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeSample', 'GutSample'],
         'examples': [{'value': 'trypsin'},
                      {'value': 'trypLE'},
                      {'value': 'collagenase'}]} })
    sample_id: str = Field(default=..., title="Sample ID", description="""Identification number of the sample. This is the fundamental unit of sampling the tissue (the specimen taken from the subject), which can be the same as the 'subject_ID', but is often different if multiple samples are taken from the same subject. Note: this is NOT a unit of multiplexing of donor samples, which should be stored in \"library\".""", json_schema_extra = { "linkml_meta": {'alias': 'sample_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of sampling of the tissue.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'SC24'}, {'value': 'SC25'}, {'value': 'SC28'}]} })
    donor_id: str = Field(default=..., title="Donor ID", description="""This must be free-text that identifies a unique individual that data were derived from.""", json_schema_extra = { "linkml_meta": {'alias': 'donor_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'donor_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of biological variation of the data.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1'},
                      {'value': 'MM_donor_1'},
                      {'value': 'LR_donor_2'}],
         'notes': ['It is strongly recommended that this identifier be designed so '
                   'that it is unique to: a given individual within the collection of '
                   'datasets that includes this dataset, and a given individual across '
                   'all collections in CELLxGENE Discover. It is strongly recommended '
                   'that "pooled" be used for observations from a sample of multiple '
                   'individuals that were not confidently assigned to a single '
                   'individual through demultiplexing. It is strongly recommended that '
                   '"unknown" ONLY be used for observations in a dataset when it is '
                   'not known which observations are from the same individual.']} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })
    author_batch_notes: Optional[str] = Field(default=None, title="Author Batch Notes", description="""Encoding of author knowledge on any further information related to likely batch effects.""", json_schema_extra = { "linkml_meta": {'alias': 'author_batch_notes',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Space for author intuition of batch effects in their dataset.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'Batch run by different personnel on different days'}]} })
    age_range: Optional[str] = Field(default=None, title="Age Range", description="""Deprecated placeholder for age range metadata.""", json_schema_extra = { "linkml_meta": {'alias': 'age_range',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })
    cell_number_loaded: Optional[int] = Field(default=None, title="Cell Number Loaded", description="""Estimated number of cells loaded for library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_number_loaded',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Can explain the number of doublets found in samples.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '5000'}, {'value': '4000'}]} })
    cell_viability_percentage: Optional[Union[Decimal, str]] = Field(default=None, title="Cell Viability Percentage", description="""If measured, per sample cell viability before library preparation (as a percentage).""", json_schema_extra = { "linkml_meta": {'alias': 'cell_viability_percentage',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'any_of': [{'range': 'decimal'}, {'range': 'string'}],
         'comments': ['Is a measure of sample quality that could be used to explain '
                      'outlier samples.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '88'},
                      {'value': '95'},
                      {'value': '93.5'},
                      {'value': 'unknown'}]} })
    cell_enrichment: str = Field(default=..., title="Cell Enrichment", description="""Specifies the cell types targeted for enrichment or depletion beyond the selection of live cells.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_enrichment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['If cell lineages were filtered, this may be a dataset exclusion '
                      'criterion.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'CL:0000057+'}, {'value': 'na'}],
         'notes': ['This must be a Cell Ontology (CL) term '
                   '(https://www.ebi.ac.uk/ols4/ontologies/cl). For cells that are '
                   'enriched, list the CL code followed by a "+". For cells that were '
                   'depleted, list the CL code followed by a "-". If no enrichment or '
                   "depletion occurred, please use 'na' (not applicable)"]} })
    development_stage_ontology_term_id: DevelopmentStage = Field(default=..., title="Development Stage Ontology Term ID", description="""Age of the subject.""", json_schema_extra = { "linkml_meta": {'alias': 'development_stage_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg',
                                 'value': 'development_stage_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Developmental stage is a key biological covariate for '
                      'interpreting cell state and comparing samples across donors.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'HsapDv:0000237'}, {'value': 'unknown'}],
         'notes': ['If organism_ontology_term_id is "NCBITaxon:9606" for *Homo '
                   'sapiens*, this should be an HsapDv term. If '
                   'organism_ontology_term_id is "NCBITaxon:10090" for *Mus musculus*, '
                   'this should be an MmusDv term.\n'
                   '\n'
                   '**Requirements for data contributors adhering to GDPR or like '
                   'standards**: HCA requests that you do not submit year-specific '
                   'terms. Refer to broader age bracket terms as needed.']} })
    disease_ontology_term_id: str = Field(default=..., title="Disease Ontology Term ID", description="""Disease, if expected to impact the sample.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'disease_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Disease has a major effect on cell state, and determines which '
                      'samples can serve as a healthy reference.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'MONDO:0005385'}, {'value': 'PATO:0000461'}],
         'notes': ['This must be a MONDO term or "PATO:0000461" for normal or '
                   'healthy.\n'
                   '\n'
                   '**Requirements for data contributors adhering to GDPR or like '
                   'standards**: In the case of disease, HCA requests that you submit '
                   'a higher order ontology term - this is especially important in the '
                   'case of rare disease.']} })
    disease_ontology_term: Optional[str] = Field(default=None, title="Disease Ontology Term", description="""Deprecated placeholder for disease ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
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
         'examples': [{'value': 'EMBL-EBI'},
                      {'value': 'Genome Institute of Singapore'}]} })
    is_primary_data: Optional[str] = Field(default=None, title="Is Primary Data", description="""This must be \"true\" if this is the canonical instance of this cellular observation and \"false\" if not. This is commonly \"false\" for meta-analyses reusing data or for secondary views of data.""", json_schema_extra = { "linkml_meta": {'alias': 'is_primary_data',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'is_primary_data'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['This helps to ensure samples are not used twice.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'true'}, {'value': 'false'}],
         'is_a': 'deprecated_slot',
         'notes': ['true; false']} })
    library_id: str = Field(default=..., title="Library ID", description="""The unique ID that is used to track libraries in the investigator's institution (should align with the publication).""", json_schema_extra = { "linkml_meta": {'alias': 'library_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['A way to track the unit of data generation. This should include '
                      'sample pooling.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'A24'}, {'value': 'NK_healthy_001'}]} })
    library_id_repository: Optional[str] = Field(default=None, title="Library ID Repository", description="""The unique ID used to track libraries from one of the following public data repositories: EGAX*, GSM*, SRX*, ERX*, DRX, HRX, CRX.""", json_schema_extra = { "linkml_meta": {'alias': 'library_id_repository',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Links a dataset back to the source from which it was ingested, '
                      'optional only if this is the same as the library_id.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'GSM1684095'}]} })
    library_preparation_batch: Optional[str] = Field(default=None, title="Library Preparation Batch", description="""Indicating which samples' libraries were prepared in the same chip/plate/etc., e.g. batch1, batch2.""", json_schema_extra = { "linkml_meta": {'alias': 'library_preparation_batch',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Sample preparation is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'batch01'}, {'value': 'batch02'}],
         'recommended': True} })
    library_sequencing_run: Optional[str] = Field(default=None, title="Library Sequencing Run", description="""The identifier (or accession number) that indicates which samples' libraries were sequenced in the same run.""", json_schema_extra = { "linkml_meta": {'alias': 'library_sequencing_run',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Library sequencing is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'run1'}, {'value': 'NV0087'}],
         'recommended': True} })
    sample_collection_method: SampleCollectionMethod = Field(default=..., title="Sample Collection Method", description="""The method the sample was physically obtained from the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'biopsy'},
                      {'value': 'brush'},
                      {'value': 'surgical resection'}]} })
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
                      'effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'AIDA_site_1'}, {'value': 'AIDA_site_2'}],
         'notes': ['It is strongly recommended that this identifier be designed so '
                   'that it is unique to a given site within the collection of '
                   "datasets that includes this site (for example, the labels 'site1', "
                   "'site2' may appear in other datasets thus rendering them "
                   'indistinguishable).']} })
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
         'comments': ['Source of batch effect & dataset exclusion criteria.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'tissue'},
                      {'value': 'organoid'},
                      {'value': 'cell culture'}]} })
    tissue_ontology_term_id: str = Field(default=..., title="Tissue Ontology Term ID", description="""The detailed anatomical location of the sample, please provide a specific UBERON term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major biological effect that needs to be assessed for '
                      'sufficient coverage in the atlas datasets.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'UBERON:0001828'}, {'value': 'UBERON:0000966'}],
         'notes': ['If tissue_type is "tissue" or "organoid", this must be the most '
                   'accurate child of UBERON:0001062 for anatomical entity. If '
                   'tissue_type is "cell culture" this must follow the requirements '
                   'for cell_type_ontology_term_id.']} })
    suspension_type: SuspensionType = Field(default=..., title="Suspension Type", description="""Specifies whether the sample contains single cells or single nuclei data.""", json_schema_extra = { "linkml_meta": {'alias': 'suspension_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'suspension_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major source of batch effect & dataset exclusion criteria.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'cell'}, {'value': 'nucleus'}, {'value': 'na'}],
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
                   '* inDrop [EFO:0008780] = "cell" or "nucleus"']} })
    sampled_site_condition: SampledSiteCondition = Field(default=..., title="Sampled Site Condition", description="""Whether the site is considered healthy, diseased or adjacent to disease.""", json_schema_extra = { "linkml_meta": {'alias': 'sampled_site_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'healthy'},
                      {'value': 'diseased'},
                      {'value': 'adjacent'}]} })
    sample_preservation_method: SamplePreservationMethod = Field(default=..., title="Sample Preservation Method", description="""Indicating if tissue was frozen, or not, at any point before library preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_preservation_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'fresh'}, {'value': 'frozen at -70C'}]} })
    sample_source: SampleSource = Field(default=..., title="Sample Source", description="""The study subgroup that the participant belongs to. This indicates whether the participant was a surgical donor (this includes patients providing blood samples or biopsies), a postmortem donor, or a living organ donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_source',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['The source of the sample (whether the sample comes from a '
                      'surgical donor, a postmortem donor or a living organ donor) can '
                      'result in different cellular profiles and hence batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'surgical donor'}, {'value': 'postmortem donor'}]} })
    tissue_ontology_term: Optional[str] = Field(default=None, title="Tissue Ontology Term", description="""Deprecated placeholder for tissue ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })


class GutSample(Sample):
    """
    Sample with Gut BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'bioNetwork': {'tag': 'bioNetwork', 'value': 'gut'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/gut'})

    radial_tissue_term: RadialTissueTerm = Field(default=..., title="Radial Tissue Term", description="""The layer of the gut that was sequenced. This depends on the chemical digestion used.""", json_schema_extra = { "linkml_meta": {'alias': 'radial_tissue_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['GutSample'],
         'examples': [{'value': 'EPI'},
                      {'value': 'LP'},
                      {'value': 'MUSC'},
                      {'value': 'SUB'},
                      {'value': 'MLN'},
                      {'value': 'Peyers patch'}]} })
    dissociation_protocol: str = Field(default=..., title="Dissociation Protocol", description="""Dissociation chemicals used during sample preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'dissociation_protocol',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeSample', 'GutSample'],
         'examples': [{'value': 'trypsin'},
                      {'value': 'trypLE'},
                      {'value': 'collagenase'}]} })
    sample_id: str = Field(default=..., title="Sample ID", description="""Identification number of the sample. This is the fundamental unit of sampling the tissue (the specimen taken from the subject), which can be the same as the 'subject_ID', but is often different if multiple samples are taken from the same subject. Note: this is NOT a unit of multiplexing of donor samples, which should be stored in \"library\".""", json_schema_extra = { "linkml_meta": {'alias': 'sample_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of sampling of the tissue.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'SC24'}, {'value': 'SC25'}, {'value': 'SC28'}]} })
    donor_id: str = Field(default=..., title="Donor ID", description="""This must be free-text that identifies a unique individual that data were derived from.""", json_schema_extra = { "linkml_meta": {'alias': 'donor_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'donor_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Fundamental unit of biological variation of the data.'],
         'domain_of': ['Donor', 'Sample'],
         'examples': [{'value': 'CR_donor_1'},
                      {'value': 'MM_donor_1'},
                      {'value': 'LR_donor_2'}],
         'notes': ['It is strongly recommended that this identifier be designed so '
                   'that it is unique to: a given individual within the collection of '
                   'datasets that includes this dataset, and a given individual across '
                   'all collections in CELLxGENE Discover. It is strongly recommended '
                   'that "pooled" be used for observations from a sample of multiple '
                   'individuals that were not confidently assigned to a single '
                   'individual through demultiplexing. It is strongly recommended that '
                   '"unknown" ONLY be used for observations in a dataset when it is '
                   'not known which observations are from the same individual.']} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })
    author_batch_notes: Optional[str] = Field(default=None, title="Author Batch Notes", description="""Encoding of author knowledge on any further information related to likely batch effects.""", json_schema_extra = { "linkml_meta": {'alias': 'author_batch_notes',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Space for author intuition of batch effects in their dataset.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'Batch run by different personnel on different days'}]} })
    age_range: Optional[str] = Field(default=None, title="Age Range", description="""Deprecated placeholder for age range metadata.""", json_schema_extra = { "linkml_meta": {'alias': 'age_range',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })
    cell_number_loaded: Optional[int] = Field(default=None, title="Cell Number Loaded", description="""Estimated number of cells loaded for library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_number_loaded',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Can explain the number of doublets found in samples.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '5000'}, {'value': '4000'}]} })
    cell_viability_percentage: Optional[Union[Decimal, str]] = Field(default=None, title="Cell Viability Percentage", description="""If measured, per sample cell viability before library preparation (as a percentage).""", json_schema_extra = { "linkml_meta": {'alias': 'cell_viability_percentage',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'any_of': [{'range': 'decimal'}, {'range': 'string'}],
         'comments': ['Is a measure of sample quality that could be used to explain '
                      'outlier samples.'],
         'domain_of': ['Sample'],
         'examples': [{'value': '88'},
                      {'value': '95'},
                      {'value': '93.5'},
                      {'value': 'unknown'}]} })
    cell_enrichment: str = Field(default=..., title="Cell Enrichment", description="""Specifies the cell types targeted for enrichment or depletion beyond the selection of live cells.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_enrichment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['If cell lineages were filtered, this may be a dataset exclusion '
                      'criterion.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'CL:0000057+'}, {'value': 'na'}],
         'notes': ['This must be a Cell Ontology (CL) term '
                   '(https://www.ebi.ac.uk/ols4/ontologies/cl). For cells that are '
                   'enriched, list the CL code followed by a "+". For cells that were '
                   'depleted, list the CL code followed by a "-". If no enrichment or '
                   "depletion occurred, please use 'na' (not applicable)"]} })
    development_stage_ontology_term_id: DevelopmentStage = Field(default=..., title="Development Stage Ontology Term ID", description="""Age of the subject.""", json_schema_extra = { "linkml_meta": {'alias': 'development_stage_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg',
                                 'value': 'development_stage_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Developmental stage is a key biological covariate for '
                      'interpreting cell state and comparing samples across donors.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'HsapDv:0000237'}, {'value': 'unknown'}],
         'notes': ['If organism_ontology_term_id is "NCBITaxon:9606" for *Homo '
                   'sapiens*, this should be an HsapDv term. If '
                   'organism_ontology_term_id is "NCBITaxon:10090" for *Mus musculus*, '
                   'this should be an MmusDv term.\n'
                   '\n'
                   '**Requirements for data contributors adhering to GDPR or like '
                   'standards**: HCA requests that you do not submit year-specific '
                   'terms. Refer to broader age bracket terms as needed.']} })
    disease_ontology_term_id: str = Field(default=..., title="Disease Ontology Term ID", description="""Disease, if expected to impact the sample.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'disease_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Disease has a major effect on cell state, and determines which '
                      'samples can serve as a healthy reference.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'MONDO:0005385'}, {'value': 'PATO:0000461'}],
         'notes': ['This must be a MONDO term or "PATO:0000461" for normal or '
                   'healthy.\n'
                   '\n'
                   '**Requirements for data contributors adhering to GDPR or like '
                   'standards**: In the case of disease, HCA requests that you submit '
                   'a higher order ontology term - this is especially important in the '
                   'case of rare disease.']} })
    disease_ontology_term: Optional[str] = Field(default=None, title="Disease Ontology Term", description="""Deprecated placeholder for disease ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'disease_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
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
         'examples': [{'value': 'EMBL-EBI'},
                      {'value': 'Genome Institute of Singapore'}]} })
    is_primary_data: Optional[str] = Field(default=None, title="Is Primary Data", description="""This must be \"true\" if this is the canonical instance of this cellular observation and \"false\" if not. This is commonly \"false\" for meta-analyses reusing data or for secondary views of data.""", json_schema_extra = { "linkml_meta": {'alias': 'is_primary_data',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'is_primary_data'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['This helps to ensure samples are not used twice.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'true'}, {'value': 'false'}],
         'is_a': 'deprecated_slot',
         'notes': ['true; false']} })
    library_id: str = Field(default=..., title="Library ID", description="""The unique ID that is used to track libraries in the investigator's institution (should align with the publication).""", json_schema_extra = { "linkml_meta": {'alias': 'library_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['A way to track the unit of data generation. This should include '
                      'sample pooling.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'A24'}, {'value': 'NK_healthy_001'}]} })
    library_id_repository: Optional[str] = Field(default=None, title="Library ID Repository", description="""The unique ID used to track libraries from one of the following public data repositories: EGAX*, GSM*, SRX*, ERX*, DRX, HRX, CRX.""", json_schema_extra = { "linkml_meta": {'alias': 'library_id_repository',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Links a dataset back to the source from which it was ingested, '
                      'optional only if this is the same as the library_id.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'GSM1684095'}]} })
    library_preparation_batch: Optional[str] = Field(default=None, title="Library Preparation Batch", description="""Indicating which samples' libraries were prepared in the same chip/plate/etc., e.g. batch1, batch2.""", json_schema_extra = { "linkml_meta": {'alias': 'library_preparation_batch',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Sample preparation is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'batch01'}, {'value': 'batch02'}],
         'recommended': True} })
    library_sequencing_run: Optional[str] = Field(default=None, title="Library Sequencing Run", description="""The identifier (or accession number) that indicates which samples' libraries were sequenced in the same run.""", json_schema_extra = { "linkml_meta": {'alias': 'library_sequencing_run',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Library sequencing is a major source of batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'run1'}, {'value': 'NV0087'}],
         'recommended': True} })
    sample_collection_method: SampleCollectionMethod = Field(default=..., title="Sample Collection Method", description="""The method the sample was physically obtained from the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_collection_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'biopsy'},
                      {'value': 'brush'},
                      {'value': 'surgical resection'}]} })
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
                      'effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'AIDA_site_1'}, {'value': 'AIDA_site_2'}],
         'notes': ['It is strongly recommended that this identifier be designed so '
                   'that it is unique to a given site within the collection of '
                   "datasets that includes this site (for example, the labels 'site1', "
                   "'site2' may appear in other datasets thus rendering them "
                   'indistinguishable).']} })
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
         'comments': ['Source of batch effect & dataset exclusion criteria.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'tissue'},
                      {'value': 'organoid'},
                      {'value': 'cell culture'}]} })
    tissue_ontology_term_id: str = Field(default=..., title="Tissue Ontology Term ID", description="""The detailed anatomical location of the sample, please provide a specific UBERON term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'tissue_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major biological effect that needs to be assessed for '
                      'sufficient coverage in the atlas datasets.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'UBERON:0001828'}, {'value': 'UBERON:0000966'}],
         'notes': ['If tissue_type is "tissue" or "organoid", this must be the most '
                   'accurate child of UBERON:0001062 for anatomical entity. If '
                   'tissue_type is "cell culture" this must follow the requirements '
                   'for cell_type_ontology_term_id.']} })
    suspension_type: SuspensionType = Field(default=..., title="Suspension Type", description="""Specifies whether the sample contains single cells or single nuclei data.""", json_schema_extra = { "linkml_meta": {'alias': 'suspension_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'suspension_type'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major source of batch effect & dataset exclusion criteria.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'cell'}, {'value': 'nucleus'}, {'value': 'na'}],
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
                   '* inDrop [EFO:0008780] = "cell" or "nucleus"']} })
    sampled_site_condition: SampledSiteCondition = Field(default=..., title="Sampled Site Condition", description="""Whether the site is considered healthy, diseased or adjacent to disease.""", json_schema_extra = { "linkml_meta": {'alias': 'sampled_site_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'healthy'},
                      {'value': 'diseased'},
                      {'value': 'adjacent'}]} })
    sample_preservation_method: SamplePreservationMethod = Field(default=..., title="Sample Preservation Method", description="""Indicating if tissue was frozen, or not, at any point before library preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_preservation_method',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Main contributor to batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'fresh'}, {'value': 'frozen at -70C'}]} })
    sample_source: SampleSource = Field(default=..., title="Sample Source", description="""The study subgroup that the participant belongs to. This indicates whether the participant was a surgical donor (this includes patients providing blood samples or biopsies), a postmortem donor, or a living organ donor.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_source',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['The source of the sample (whether the sample comes from a '
                      'surgical donor, a postmortem donor or a living organ donor) can '
                      'result in different cellular profiles and hence batch effects.'],
         'domain_of': ['Sample'],
         'examples': [{'value': 'surgical donor'}, {'value': 'postmortem donor'}]} })
    tissue_ontology_term: Optional[str] = Field(default=None, title="Tissue Ontology Term", description="""Deprecated placeholder for tissue ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Sample'],
         'is_a': 'deprecated_slot'} })


class MusculoskeletalDataset(Dataset):
    """
    Dataset with Musculoskeletal BioNetwork–specific metadata requirements.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'bioNetwork': {'tag': 'bioNetwork',
                                        'value': 'musculoskeletal'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/musculoskeletal'})

    ambient_count_correction: str = Field(default=..., title="Ambient Count Correction", description="""Software used to correct ambient RNA counts, or 'none'.""", json_schema_extra = { "linkml_meta": {'alias': 'ambient_count_correction',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeDataset', 'GutDataset', 'MusculoskeletalDataset'],
         'examples': [{'value': 'none'}, {'value': 'soupx'}, {'value': 'cellbender'}]} })
    doublet_detection: str = Field(default=..., title="Doublet Detection", description="""Was doublet detection software used during CELLxGENE processing? If so, which software?""", json_schema_extra = { "linkml_meta": {'alias': 'doublet_detection',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['AdiposeDataset', 'GutDataset', 'MusculoskeletalDataset'],
         'examples': [{'value': 'none'},
                      {'value': 'doublet_finder'},
                      {'value': 'manual'}]} })
    alignment_software: str = Field(default=..., title="Alignment Software", description="""Protocol used for alignment analysis, please specify which version was used e.g. cell ranger 2.0, 2.1.1 etc.""", json_schema_extra = { "linkml_meta": {'alias': 'alignment_software',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects which cells are filtered per dataset, and which reads '
                      '(introns and exons or only exons) are counted as part of the '
                      'reported transcriptome. This can convey batch effects.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'cell ranger 3.0.1'},
                      {'value': 'kallisto bustools'},
                      {'value': 'GSNAP'}]} })
    assay_ontology_term_id: str = Field(default=..., title="Assay Ontology Term ID", description="""Platform used for single cell library construction.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'assay_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Major source of batch effect and dataset filtering criterion.'],
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
                   '- Visium Spatial Gene Expression "EFO:0010961"']} })
    assay_ontology_term: Optional[str] = Field(default=None, title="Assay Ontology Term", description="""Deprecated placeholder for assay ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'assay_ontology_term',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    batch_condition: Optional[list[str]] = Field(default=None, title="Batch Condition", description="""Name of the covariate that confers the dominant batch effect in the data as judged by the data contributor. The name provided here should be the label by which this covariate is stored in the AnnData object.""", json_schema_extra = { "linkml_meta": {'alias': 'batch_condition',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'batch_condition'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Multiple batch conditions as a JSON array',
                       'value': '["patient", "seqBatch"]'}],
         'notes': ['Values must refer to cell metadata keys in obs. Together, these '
                   'keys define the batches that a normalisation or integration '
                   'algorithm should be aware of. For example if "patient" and '
                   '"seqBatch" are keys of vectors of cell metadata, either '
                   '["patient"], ["seqBatch"], or ["patient", "seqBatch"] are valid '
                   'values.']} })
    comments: Optional[str] = Field(default=None, title="Comments", description="""Other technical or experimental covariates that could affect the quality or batch of the sample. Must not contain identifiers. This field is designed to capture potential challenges for data integration not captured elsewhere.""", json_schema_extra = { "linkml_meta": {'alias': 'comments',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    consortia: Optional[str] = Field(default=None, title="Consortia", description="""Deprecated placeholder for consortia information.""", json_schema_extra = { "linkml_meta": {'alias': 'consortia',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'is_a': 'deprecated_slot'} })
    contact_email: str = Field(default=..., title="Contact Email", description="""Contact name and email of the submitting person""", json_schema_extra = { "linkml_meta": {'alias': 'contact_email',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset']} })
    default_embedding: Optional[str] = Field(default=None, title="Default Embedding", description="""The value must match a key to an embedding in obsm for the embedding to display by default in CELLxGENE Explorer.""", json_schema_extra = { "linkml_meta": {'alias': 'default_embedding',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'default_embedding'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset']} })
    description: str = Field(default=..., title="Description", description="""Short description of the dataset""", json_schema_extra = { "linkml_meta": {'alias': 'description',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'}},
         'domain_of': ['Dataset']} })
    gene_annotation_version: str = Field(default=..., title="Gene Annotation Version", description="""Ensembl release version accession number. Some common codes include: GRCh38.p12 = GCF_000001405.38 GRCh38.p13 = GCF_000001405.39 GRCh38.p14 = GCF_000001405.40""", json_schema_extra = { "linkml_meta": {'alias': 'gene_annotation_version',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'v110'}, {'value': 'GCF_000001405.40'}],
         'notes': ['http://www.ensembl.org/info/website/archives/index.html or '
                   'NCBI/RefSeq']} })
    intron_inclusion: Optional[YesNoEnum] = Field(default=None, title="Intron Inclusion", description="""Were introns included during read counting in the alignment process?""", json_schema_extra = { "linkml_meta": {'alias': 'intron_inclusion',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Affects the number of reads per cell called in a sample.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'yes'}, {'value': 'no'}]} })
    protocol_url: Optional[str] = Field(default=None, title="Protocol URL", description="""The protocols.io URL (if none exists, please use the BioRxiv URL) for the full experimental protocol; or if multiple protocols exist please list them e.g. sample preparation protocol / sequencing protocol.""", json_schema_extra = { "linkml_meta": {'alias': 'protocol_url',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Useful to look up protocol data that can provide insight on '
                      'batch effects. As protocols can sometimes apply to a subset of '
                      'the study, we capture this at a sample level. This information '
                      'may not always be available.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'https://www.biorxiv.org/content/early/2017/09/24/193219'}]} })
    publication_doi: Optional[str] = Field(default=None, title="Publication DOI", description="""The publication digital object identifier (doi) for the protocol. If no pre-print nor publication exists, please write 'not applicable'.""", json_schema_extra = { "linkml_meta": {'alias': 'publication_doi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'}},
         'domain_of': ['Dataset'],
         'examples': [{'value': '10.1016/j.cell.2016.07.054'}]} })
    reference_genome: ReferenceGenomeEnum = Field(default=..., title="Reference Genome", description="""Reference genome used for alignment.""", json_schema_extra = { "linkml_meta": {'alias': 'reference_genome',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Possible source of batch effect and confounder for some '
                      'biological analysis.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'GRCh38'}, {'value': 'GRCh37'}]} })
    sequenced_fragment: SequencedFragmentEnum = Field(default=..., title="Sequenced Fragment", description="""Which part of the RNA transcript was targeted for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequenced_fragment',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['May be a source of batch effect that has to be tested.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': '3 prime tag'}, {'value': 'full length'}]} })
    sequencing_platform: Optional[str] = Field(default=None, title="Sequencing Platform", description="""Platform used for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'sequencing_platform',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['This captures potential strand hopping which may cause data '
                      'quality issues.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'EFO:0008563'}],
         'notes': ['Values should be "subClassOf" ["EFO:0002699"] - '
                   'https://www.ebi.ac.uk/ols4/ontologies/efo/classes?iri=http%3A%2F%2Fwww.ebi.ac.uk%2Fefo%2FEFO_0002699']} })
    study_pi: list[str] = Field(default=..., title="Study PI", description="""Principal Investigator(s) leading the study where the data is/was used.""", json_schema_extra = { "linkml_meta": {'alias': 'study_pi',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'domain_of': ['Dataset'],
         'examples': [{'description': 'Principal Investigator in Last name,First '
                                      'name,Middle initial format',
                       'value': 'Teichmann,Sarah,A.'}]} })
    title: str = Field(default=..., title="Title", description="""This text describes and differentiates the dataset from other datasets in the same collection. It is strongly recommended that each dataset title in a collection is unique and does not depend on other metadata such as a different assay to disambiguate it from other datasets in the collection.""", json_schema_extra = { "linkml_meta": {'alias': 'title',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'uns'},
                         'cxg': {'tag': 'cxg', 'value': 'title'},
                         'entrySheetRequired': {'tag': 'entrySheetRequired',
                                                'value': False},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Distinguishes this dataset from others in the same collection.'],
         'domain_of': ['Dataset'],
         'examples': [{'value': 'Cells of the adult human heart collection is "All — '
                                'Cells of the adult human heart"'}]} })
    dataset_id: str = Field(default=..., title="Dataset ID", description="""A unique identifier for each dataset in the study. This should be unique to the study.""", json_schema_extra = { "linkml_meta": {'alias': 'dataset_id', 'domain_of': ['Dataset', 'Donor', 'Sample']} })


class MusculoskeletalDonorTier2(ConfiguredBaseModel):
    """
    Musculoskeletal BioNetwork Tier 2 donor metadata, collected under managed access.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'baseClass': {'tag': 'baseClass', 'value': 'Donor'},
                         'bioNetwork': {'tag': 'bioNetwork',
                                        'value': 'musculoskeletal'},
                         'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/musculoskeletal',
         'mixin': True})

    age_value: Optional[int] = Field(default=None, title="Age Value", description="""Age of donor at the time of sample collection. Specify the age unit (week, month, year) in age_unit.""", json_schema_extra = { "linkml_meta": {'alias': 'age_value',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Age can impact cellular and molecular phenotypes.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '20'}, {'value': '32'}, {'value': '56'}]} })
    age_unit: Optional[str] = Field(default=None, title="Age Unit", description="""Age unit (week, month, year) for the age_value.""", json_schema_extra = { "linkml_meta": {'alias': 'age_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Age can impact cellular and molecular phenotypes.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })
    bmi: Optional[Decimal] = Field(default=None, title="BMI", description="""Body mass index of the donor at the time of collection.""", json_schema_extra = { "linkml_meta": {'alias': 'bmi',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['May serve as a covariate for analysis of human diversity. If '
                      'height or weight is not provided but BMI is, fill here.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '36.4'}, {'value': '19.2'}, {'value': '27'}]} })
    height: Optional[int] = Field(default=None, title="Height", description="""Height of donor in cm at the time of collection.""", json_schema_extra = { "linkml_meta": {'alias': 'height',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Highly heritable (PMID: 36224396); together with weight can '
                      'allow for computation of body-mass index, which may serve as a '
                      'covariate for analyses of human diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '160'}, {'value': '137'}, {'value': '203'}]} })
    weight: Optional[int] = Field(default=None, title="Weight", description="""Weight of donor in kilograms at the time of collection.""", json_schema_extra = { "linkml_meta": {'alias': 'weight',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Together with height can allow for computation of body-mass '
                      'index, which may serve as a covariate for analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '50'}, {'value': '80'}]} })
    genderidentity_selfreported: Optional[str] = Field(default=None, title="Gender Identity Self-Reported", description="""Donor self-reported gender identity.""", json_schema_extra = { "linkml_meta": {'alias': 'genderidentity_selfreported',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Gender identity information may be important for studies '
                      'involving hormonal treatments, etc.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Female Gender'},
                      {'value': 'Male Gender'},
                      {'value': 'Non-Binary Gender'},
                      {'value': 'Other Gender'},
                      {'value': 'Agender'},
                      {'value': 'Gender Fluid'},
                      {'value': 'Gender Identifier X'},
                      {'value': 'Genderqueer'},
                      {'value': 'Transgender'},
                      {'value': 'Two-spirit'}]} })
    ethnicity_selfreported_freetext: Optional[str] = Field(default=None, title="Ethnicity Self-Reported Free Text", description="""Donor self-reported ethnicity (or ethnicities) in free-text; can include tribe, dialect group, etc. If race information is submitted under this field, please ensure that the question(s) and response options posed to donors are included in the next metadata category (\"ethnicity_question_text\"). Separate multiple entries with a comma.""", json_schema_extra = { "linkml_meta": {'alias': 'ethnicity_selfreported_freetext',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Self-reported ethnicity information can encompass language, '
                      'religion, tribe, and cultural factors, beyond genetic '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2']} })
    ethnicity_question_text: Optional[str] = Field(default=None, title="Ethnicity Question Text", description="""Question and response options posed to donors for collecting metadata on donor self-reported ethnicity and / or tribe and / or dialect group and / or race etc.""", json_schema_extra = { "linkml_meta": {'alias': 'ethnicity_question_text',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Provides context on the method for collecting self-reported '
                      'ethnicity, tribe, dialect group, or race information. '
                      'Self-reported ethnicity information can encompass language, '
                      'religion, tribe, and cultural factors, beyond genetic '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '"What is your ethnicity?"'},
                      {'value': '"Are you Hispanic/Latino?"'},
                      {'value': 'Example from All of Us "Which categories describe '
                                'you? Select all that apply. Note You may select more '
                                'than one group. American Indian or Alaska Native (for '
                                'example, Aztec, Blackfeet Tribe, Mayan, Navajo '
                                'Nation, Native Village of Barrow (Utqiagvik) Inupiat '
                                'Traditional Government, Nome Eskimo Community, etc.)* '
                                'Asian (for example, Asian Indian, Chinese, Filipino, '
                                'Japanese, Korean, Vietnamese, etc.)* Black, African '
                                'American, or African (for example, African American, '
                                'Ethiopian, Haitian, Jamaican, Nigerian, Somali, '
                                'etc.)* Hispanic, Latino, or Spanish (for example, '
                                'Columbian, Cuban, Dominican, Mexican or Mexican '
                                'American, Puerto Rican, Salvadoran, etc.)* Middle '
                                'Eastern or North African (for example, Algerian, '
                                'Egyptian, Iranian, Lebanese, Moroccan, Syrian, etc.)* '
                                'Native Hawaiian or other Pacific Islander (for '
                                'example, Chamorro, Fijian, Marshallese, Native '
                                'Hawaiian, Tongan, etc.)* White (for example, English, '
                                'European, French, German, Irish, Italian, Polish, '
                                'etc.)* None of these fully describe me (optional free '
                                'text answer) Prefer not to answer" not collected, not '
                                'available'}]} })
    language_donor_primary_language: Optional[str] = Field(default=None, title="Language Donor Primary Language", description="""Primary language(s), spoken by donor. Can include dialects (for example, Hokkien).""", json_schema_extra = { "linkml_meta": {'alias': 'language_donor_primary_language',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Primary language(s) may contain information relevant to '
                      "ancestry, as well as a donor's environmental and cultural "
                      'context.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Mandarin Chinese'},
                      {'value': 'Hokkien'},
                      {'value': 'Bahasa Melayu'},
                      {'value': 'Tamil'},
                      {'value': 'Hausa'},
                      {'value': 'Yoruba'},
                      {'value': 'Swahili'}]} })
    geography_currentresidence_location_country_state: Optional[str] = Field(default=None, title="Geography Current Residence Location Country State", description="""Country and state of donor's current residence at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_location_country_state',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a coarser level (country '
                      'and state).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'United Kingdom'},
                      {'value': 'Massachusetts USA'},
                      {'value': 'New South Wales Australia'},
                      {'value': 'Bauchi State'},
                      {'value': 'Nigeria'}]} })
    geography_currentresidence_location_granular: Optional[str] = Field(default=None, title="Geography Current Residence Location Granular", description="""Nearest city, town, or village to location of donor's current residence at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_location_granular',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a more granular level '
                      '(city / town / village).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'Cambridge'},
                      {'value': 'Boston'},
                      {'value': 'Kingston'}]} })
    occupation: Optional[str] = Field(default=None, title="Occupation", description="""Specify the occupation of the donor.""", json_schema_extra = { "linkml_meta": {'alias': 'occupation',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Should be mapped to OccO Occupation Ontology '
                                'OCCO:00000001'}],
         'notes': ['[OCCO '
                   'ontology](https://www.ebi.ac.uk/ols4/ontologies/occo/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FOCCO_00000001?lang=en)']} })
    comorbidities: Optional[str] = Field(default=None, title="Comorbidities", description="""Indicate all comorbidities/ secondary diagnoses of the donor (primary diagnosis was asked in disease_ontology_term_id field of tier 1 metadata). This must be a MONDO term. Separate multiple entries with a comma.""", json_schema_extra = { "linkml_meta": {'alias': 'comorbidities',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'MONDO:0005044'}, {'value': 'MONDO:0005148'}],
         'notes': ['[MONDO ontology](https://www.ebi.ac.uk/ols4/ontologies/mondo)']} })
    genotype: Optional[str] = Field(default=None, title="Genotype", description="""Genotype of the biomaterial.""", json_schema_extra = { "linkml_meta": {'alias': 'genotype',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'DRB1 0401 protective allele'},
                      {'value': 'HLA-B*3901 allele'}]} })
    medication: Optional[str] = Field(default=None, title="Medication", description="""List of prescription medication consumed by the donor at time of sample collection. Should be an NCIT ontology term""", json_schema_extra = { "linkml_meta": {'alias': 'medication',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Medication consumption may be a covariate / exclusion criterion '
                      'in analyses of human diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'atorvastatin'},
                      {'value': 'brevicon'},
                      {'value': 'chlorthalidone'}],
         'notes': ['[NCIT ontology '
                   'term](https://www.ebi.ac.uk/ols4/ontologies/ncit/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FNCIT_C1908?lang=en)']} })
    diet_meat_consumption: Optional[str] = Field(default=None, title="Diet Meat Consumption", description="""Dietary patterns of donor – meat (chicken, seafood, fish, pork, lamb, beef, etc.) consumption versus meat-free diet – at time of sample collection. Fill yes if donor consumes meat or no if donor does not consumes meat.""", json_schema_extra = { "linkml_meta": {'alias': 'diet_meat_consumption',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Diet can impact cellular and molecular phenotypes.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'yes'}, {'value': 'no'}],
         'notes': ['yes; no']} })
    medical_test_results: Optional[str] = Field(default=None, title="Medical Test Results", description="""Results from medical tests performed on the individual.""", json_schema_extra = { "linkml_meta": {'alias': 'medical_test_results',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'lipid panel shows normal level of LDL (124 mg/dL)'},
                      {'value': 'HIV, HBV, HCV: Negative'}]} })
    treatments: Optional[str] = Field(default=None, title="Treatments", description="""Treatments the individual has undergone prior to biomaterial collection.""", json_schema_extra = { "linkml_meta": {'alias': 'treatments',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Patient treated with antibiotics for a urinary tract '
                                'infection'},
                      {'value': 'Patient treated with chemotherapy (Epirubicin, '
                                'cisplatin, capecitabine) to treat stomach cancer'}]} })
    previous_surgery: Optional[str] = Field(default=None, title="Previous Surgery", description="""Specify the type of previous surgery the individual has undergone prior to biomaterial collection.""", json_schema_extra = { "linkml_meta": {'alias': 'previous_surgery',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2']} })
    previous_surgery_relative_time_point: Optional[int] = Field(default=None, title="Previous Surgery Relative Time Point", description="""Indicate the time interval between the surgery and the sample collection in Previous surgery Relative Time Unit""", json_schema_extra = { "linkml_meta": {'alias': 'previous_surgery_relative_time_point',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': '4'}, {'value': '37'}, {'value': '58'}]} })
    previous_surgery_relative_time_unit: Optional[str] = Field(default=None, title="Previous Surgery Relative Time Unit", description="""Indicate the Time units of the time interval between the surgery and the sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'previous_surgery_relative_time_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })
    history_of_injury_type: Optional[str] = Field(default=None, title="History of Injury Type", description="""Specify the type of injury the individual underwent in the area of the collected biomaterial.""", json_schema_extra = { "linkml_meta": {'alias': 'history_of_injury_type',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'ankle injury'},
                      {'value': 'burn'},
                      {'value': 'spinal cord injury'}]} })
    history_of_injury_type_relative_time_point: Optional[int] = Field(default=None, title="History of Injury Type Relative Time Point", description="""Indicate the time interval between the injury and the sample collection in History of injury relative time unit.""", json_schema_extra = { "linkml_meta": {'alias': 'history_of_injury_type_relative_time_point',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': '4'}, {'value': '37'}, {'value': '58'}]} })
    history_of_injury_type_relative_time_unit: Optional[str] = Field(default=None, title="History of Injury Type Relative Time Unit", description="""Indicate the Time units of the time interval between the injury and the sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'history_of_injury_type_relative_time_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })
    alcohol_status: Optional[str] = Field(default=None, title="Alcohol Status", description="""Does the donor have drink/ drank/ never drank alcohol?""", json_schema_extra = { "linkml_meta": {'alias': 'alcohol_status',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'active'}, {'value': 'former'}, {'value': 'never'}],
         'notes': ['active; former; never']} })
    alcohol_type: Optional[str] = Field(default=None, title="Alcohol Type", description="""Types of alcoholic beverages consumed.""", json_schema_extra = { "linkml_meta": {'alias': 'alcohol_type',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'beer'}, {'value': 'liquor'}, {'value': 'wine'}],
         'notes': ['beer; liquor; wine']} })
    alcohol_usage_duration: Optional[int] = Field(default=None, title="Alcohol Usage Duration", description="""Frequency of alcohol intake per week.""", json_schema_extra = { "linkml_meta": {'alias': 'alcohol_usage_duration',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': '3'}, {'value': '14'}, {'value': '21'}]} })
    alcohol_units: Optional[Decimal] = Field(default=None, title="Alcohol Units", description="""Alcohol consumption of donor in alcohol units per week (strength (ABV) x volume (ml) ÷ 1,000).""", json_schema_extra = { "linkml_meta": {'alias': 'alcohol_units',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': '0.4'}, {'value': '7'}, {'value': '14.9'}]} })
    smoking_status: Optional[str] = Field(default=None, title="Smoking Status", description="""If the donor smokes/smoked or not.""", json_schema_extra = { "linkml_meta": {'alias': 'smoking_status',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Smoking may impact cellular and molecular phenotypes, and can '
                      'serve as a covariate for human diversity analyses.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'active'}, {'value': 'former'}, {'value': 'never'}],
         'notes': ['active; former; never']} })
    years_since_smoking_cessation: Optional[int] = Field(default=None, title="Years Since Smoking Cessation", description="""If smoking status is \"former\", specify the number of years since smoking cessation, if available.""", json_schema_extra = { "linkml_meta": {'alias': 'years_since_smoking_cessation',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': '1'}, {'value': '4'}, {'value': '12'}]} })
    smoking_pack_years: Optional[Decimal] = Field(default=None, title="Smoking Pack Years", description="""Estimated number of packs (20 cigarettes) smoked per day multiplied by the number of years subject was smoking.""", json_schema_extra = { "linkml_meta": {'alias': 'smoking_pack_years',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': '4.55'}, {'value': '12'}, {'value': '49.5'}]} })
    nutritional_state: Optional[str] = Field(default=None, title="Nutritional State", description="""Nutritional state of individual at time of biomaterial collection.""", json_schema_extra = { "linkml_meta": {'alias': 'nutritional_state',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'normal'},
                      {'value': 'fasting'},
                      {'value': 'feeding tube removed'}],
         'notes': ['normal; fasting; feeding tube removed']} })
    physical_activity_physical_exposure: Optional[str] = Field(default=None, title="Physical Activity / Physical Exposure", description="""Indicate the habitual level of physical activity and regular physical activities""", json_schema_extra = { "linkml_meta": {'alias': 'physical_activity_physical_exposure',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'active -  football, tennis'}, {'value': 'sedentary'}]} })
    handedness: Optional[str] = Field(default=None, title="Handedness", description="""Dominant hand of the donor""", json_schema_extra = { "linkml_meta": {'alias': 'handedness',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'left'},
                      {'value': 'right'},
                      {'value': 'ambidextrous'},
                      {'value': 'unknown'}],
         'notes': ['left; right; ambidextrous; unknown']} })
    microanatomical_region: Optional[str] = Field(default=None, title="Microanatomical Region", description="""Where in relation to other anatomical landmarks was the tissue collected from?""", json_schema_extra = { "linkml_meta": {'alias': 'microanatomical_region',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalDonorTier2'],
         'examples': [{'value': 'myotendinous junction, trabecular, enthesis'}]} })
    geography_collectionsite_latitude_longitude: Optional[str] = Field(default=None, title="Geography Collectionsite Latitude Longitude", description="""Latitude and longitude GPS coordinates of collection site in decimal degrees.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_collectionsite_latitude_longitude',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Contains information relevant for geographical diversity of '
                      'donors; possible proxy for environmental exposures.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '1.3, 103.8'}, {'value': 'not_sharable'}]} })
    geography_currentresidence_duration: Optional[int] = Field(default=None, title="Geography Currentresidence Duration", description="""Duration of residence, in years, rounded up to the nearest whole number, at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_duration',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Indication of duration of environmental exposure relating to '
                      'current residence.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '20'}, {'value': '37'}, {'value': '45'}]} })
    geography_currentresidence_urbanrural: Optional[str] = Field(default=None, title="Geography Currentresidence Urban Rural", description="""Urban, suburban, or rural descriptor of current residence.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_currentresidence_urbanrural',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Contains information on environmental exposure relating to '
                      'current residence'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'urban'}, {'value': 'suburban'}, {'value': 'rural'}],
         'notes': ['urban; suburban; rural']} })
    geography_placeofbirth_location_country_state: Optional[str] = Field(default=None, title="Geography Place of Birth Location Country State", description="""Country and state of place of birth.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_location_country_state',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a coarser level (country '
                      'and state).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'United Kingdom'},
                      {'value': 'Massachusetts USA'},
                      {'value': 'New South Wales Australia'},
                      {'value': 'Bauchi State'},
                      {'value': 'Nigeria'}]} })
    geography_placeofbirth_location_granular: Optional[str] = Field(default=None, title="Geography Place of Birth Location Granular", description="""Nearest city, town, or village to location of place of birth.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_location_granular',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Geographical diversity of donors, at a more granular level '
                      '(city / town / village).'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singapore'},
                      {'value': 'Cambridge'},
                      {'value': 'Boston'},
                      {'value': 'Kingston'}]} })
    geography_placeofbirth_duration: Optional[int] = Field(default=None, title="Geography Place of Birth Duration", description="""Duration of residence, in years, rounded up to the nearest whole number.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_duration',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Indication of duration of environmental exposure relating to '
                      'place of birth.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '20'}, {'value': '37'}, {'value': '45'}]} })
    geography_placeofbirth_urbanrural: Optional[str] = Field(default=None, title="Geography Place of Birth Urban Rural", description="""Urban, suburban, or rural descriptor of place of birth.""", json_schema_extra = { "linkml_meta": {'alias': 'geography_placeofbirth_urbanrural',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Contains information on environmental exposure relating to '
                      'place of birth'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'urban'}, {'value': 'suburban'}, {'value': 'rural'}],
         'notes': ['urban; suburban; rural']} })
    ethnicity_parents_selfreported_freetext: Optional[str] = Field(default=None, title="Ethnicity Parents Self-Reported Freetext", description="""Donor's parents' self-reported ethnicity (or ethnicities) in free-text; can include tribe, dialect group, etc. Separate multiple entries with a comma.""", json_schema_extra = { "linkml_meta": {'alias': 'ethnicity_parents_selfreported_freetext',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Self-reported ethnicity information can encompass language, '
                      'religion, tribe, and cultural factors, beyond genetic '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Singaporean Chinese'},
                      {'value': 'Singaporean Malay'},
                      {'value': 'Singaporean Indian'},
                      {'value': 'Haitian'},
                      {'value': 'Nigerian Hausa'},
                      {'value': 'Ghana Hausa'},
                      {'value': 'Benin Kanuri'},
                      {'value': 'Nigerian Kanuri'},
                      {'value': 'Igbo'},
                      {'value': 'Luo'},
                      {'value': 'Herero'},
                      {'value': 'Garifuna'},
                      {'value': 'Kalinago'}]} })
    language_mother_father_tongue: Optional[str] = Field(default=None, title="Language Mother Father Tongue", description="""Ancestral language(s), spoken by parents (\"mother tongue\" and / or \"father tongue\") and / or grandparents. Can include dialects (for example, Hokkien).""", json_schema_extra = { "linkml_meta": {'alias': 'language_mother_father_tongue',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Mother and father tongues may contain information relevant to '
                      'ancestry.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'Mandarin Chinese'},
                      {'value': 'Hokkien'},
                      {'value': 'Bahasa Melayu'},
                      {'value': 'Tamil'},
                      {'value': 'Hausa'},
                      {'value': 'Yoruba'},
                      {'value': 'Swahili'}]} })
    menarche_age: Optional[int] = Field(default=None, title="Menarche Age", description="""Age at menarche, rounded to nearest whole number.""", json_schema_extra = { "linkml_meta": {'alias': 'menarche_age',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Age at menarche may be a covariate in analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '13'}, {'value': '12'}, {'value': '16'}]} })
    reproductive_menopause: Optional[str] = Field(default=None, title="Reproductive Menopause", description="""Menopausal status of donor at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'reproductive_menopause',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Menopausal status may be a covariate in analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': 'pre-menopausal'},
                      {'value': 'peri-menopausal'},
                      {'value': 'post-menopausal'},
                      {'value': 'post-menopausal (induced)'},
                      {'value': 'not applicable'}],
         'notes': ['pre-menopausal; peri-menopausal; post-menopausal; post-menopausal '
                   '(induced); not applicable']} })
    reproductive_number_children: Optional[int] = Field(default=None, title="Reproductive Number Children", description="""Number of children (full-term pregnancies) the donor has given birth to at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'reproductive_number_children',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Number of children (full-term pregnancies) may be a covariate '
                      'in analyses of human diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '0'}, {'value': '2'}, {'value': '3'}]} })
    reproductive_number_pregnancies: Optional[int] = Field(default=None, title="Reproductive Number Pregnancies", description="""Number of pregnancies the donor has had at time of sample collection.""", json_schema_extra = { "linkml_meta": {'alias': 'reproductive_number_pregnancies',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'comments': ['Number of pregnancies may be a covariate in analyses of human '
                      'diversity.'],
         'domain_of': ['GeneticDiversityDonorTier2', 'MusculoskeletalDonorTier2'],
         'examples': [{'value': '2'}, {'value': '3'}, {'value': '5'}]} })


class MusculoskeletalSampleTier2(ConfiguredBaseModel):
    """
    Musculoskeletal BioNetwork Tier 2 sample metadata, collected under managed access.
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'annotations': {'baseClass': {'tag': 'baseClass', 'value': 'Sample'},
                         'bioNetwork': {'tag': 'bioNetwork',
                                        'value': 'musculoskeletal'},
                         'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/bionetwork/musculoskeletal',
         'mixin': True})

    collected_tissue_processing: Optional[str] = Field(default=None, title="Collected Tissue Processing", description="""A general description of the protocol. If possible specify in what container the tissue was collected in, and if it was processed prior to storage or dissociation""", json_schema_extra = { "linkml_meta": {'alias': 'collected_tissue_processing',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'tissue collected in DMEM/F12 containing 10% FCS and '
                                'washed in PBS. Frozen within 2h of surgery after all '
                                'fat trimmed off.'}]} })
    tissue_transportation: Optional[str] = Field(default=None, title="Tissue Transportation", description="""Was the sample transported at all? What are the details?""", json_schema_extra = { "linkml_meta": {'alias': 'tissue_transportation',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'snap frozen tissue shipped from Argentina to the UK '
                                'on dry ice.'}]} })
    time_to_laboratory: Optional[Decimal] = Field(default=None, title="Time to Laboratory", description="""Transit time in hours between tissue collection and tissue processing, meaning either storage in the laboratory or processing for sequencing.""", json_schema_extra = { "linkml_meta": {'alias': 'time_to_laboratory',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': '1.5'}, {'value': '2'}]} })
    side_of_tissue_collected: Optional[str] = Field(default=None, title="Side of Tissue Collected", description="""The side of the donor the sample was collected from.""", json_schema_extra = { "linkml_meta": {'alias': 'side_of_tissue_collected',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'left'},
                      {'value': 'right'},
                      {'value': 'main-axis'},
                      {'value': 'unknown'}],
         'notes': ['left; right; main-axis; unknown']} })
    sample_storage_method: Optional[str] = Field(default=None, title="Sample Storage Method", description="""The method by which a biomaterial was stored before tissue dissociation or processing""", json_schema_extra = { "linkml_meta": {'alias': 'sample_storage_method',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'ambient temperature'},
                      {'value': 'cut slide'},
                      {'value': 'fresh'},
                      {'value': 'frozen at -70C'},
                      {'value': 'frozen at -80C'},
                      {'value': 'frozen at -150C'},
                      {'value': 'frozen in liquid nitrogen'},
                      {'value': 'frozen in vapor phase'},
                      {'value': 'paraffin block'},
                      {'value': 'RNAlater at 4C'},
                      {'value': 'RNAlater at 25C'},
                      {'value': 'RNAlater at -20C'}],
         'notes': ['ambient temperature; cut slide; fresh; frozen at -70C; frozen at '
                   '-80C; frozen at -150C; frozen in liquid nitrogen; frozen in vapor '
                   'phase; paraffin block; RNAlater at 4C; RNAlater at 25C; RNAlater '
                   'at -20C']} })
    sample_storage_relative_time_point: Optional[int] = Field(default=None, title="Sample Storage Relative Time Point", description="""Indicate the time interval between the sample collection and the sample storage in sample storage relative time units.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_storage_relative_time_point',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': '4'}, {'value': '37'}, {'value': '58'}]} })
    sample_storage_relative_time_unit: Optional[str] = Field(default=None, title="Sample Storage Relative Time Unit", description="""Indicate the Time units of the time interval between the sample collection and the sample storage.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_storage_relative_time_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })
    sample_dissociation_relative_time_point: Optional[int] = Field(default=None, title="Sample Dissociation Relative Time Point", description="""Indicate the time interval between the sample collection and the sample dissociation in sample dissociation relative time unit.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_dissociation_relative_time_point',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': '4'}, {'value': '37'}, {'value': '58'}]} })
    sample_dissociation_relative_time_unit: Optional[str] = Field(default=None, title="Sample Dissociation Relative Time Unit", description="""Indicate the Time units of the time interval between the sample collection and the sample dissociation.""", json_schema_extra = { "linkml_meta": {'alias': 'sample_dissociation_relative_time_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })
    digestion_temperature: Optional[str] = Field(default=None, title="Digestion Temperature", description="""The temperature that the tissue was digested with the digestion solution in Celsius degree or hot/ cold""", json_schema_extra = { "linkml_meta": {'alias': 'digestion_temperature',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': '42'}, {'value': '37'}, {'value': 'cold'}]} })
    dissociation_description: Optional[str] = Field(default=None, title="Dissociation Description", description="""A general description for the dissociation protocol of the tissue.""", json_schema_extra = { "linkml_meta": {'alias': 'dissociation_description',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2']} })
    dissociation_doi: Optional[str] = Field(default=None, title="Dissociation DOI", description="""The publication or protocols.io digital object identifier (doi) for the protocol.""", json_schema_extra = { "linkml_meta": {'alias': 'dissociation_doi',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': '10.1073/pnas.2404775131'},
                      {'value': '10.1016/j.ajog.2016.07.031'}]} })
    cell_suspension_storage_time: Optional[int] = Field(default=None, title="Cell Suspension Storage Time", description="""Length of time the biomaterial was stored prior to library prepration in Storage time units.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_suspension_storage_time',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': '4'}, {'value': '37'}, {'value': '58'}]} })
    cell_suspension_storage_time_unit: Optional[str] = Field(default=None, title="Cell Suspension Storage Time Unit", description="""A term that may be associated with a time unit-related ontology term.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_suspension_storage_time_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })
    library_prep_relative_time_point: Optional[int] = Field(default=None, title="Library Prep Relative Time Point", description="""Indicate the time interval between the sample collection and the library preparation in library preparation relative time unit.""", json_schema_extra = { "linkml_meta": {'alias': 'library_prep_relative_time_point',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': '4'}, {'value': '37'}, {'value': '58'}]} })
    library_prep_relative_time_unit: Optional[str] = Field(default=None, title="Library Prep Relative Time Unit", description="""Indicate the Time units of the time interval between the sample collection and the library preparation.""", json_schema_extra = { "linkml_meta": {'alias': 'library_prep_relative_time_unit',
         'annotations': {'tier': {'tag': 'tier', 'value': 'Tier 2'}},
         'domain_of': ['MusculoskeletalSampleTier2'],
         'examples': [{'value': 'day'},
                      {'value': 'week'},
                      {'value': 'month'},
                      {'value': 'year'}],
         'notes': ['day; week; month; year']} })


class Cell(ConfiguredBaseModel):
    """
    A single cell derived from a sample
    """
    linkml_meta: ClassVar[LinkMLMeta] = LinkMLMeta({'from_schema': 'https://github.com/clevercanary/hca-validation-tools/schema/cell'})

    author_cell_type: Optional[str] = Field(default=None, title="Author Cell Type", description="""Encoding of author intuition of cellular annotation in the dataset.

Use `author_cell_type` for original source datasets where `cell_type_ontology_term_id` is not available.""", json_schema_extra = { "linkml_meta": {'alias': 'author_cell_type',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Encoding of author intuition of cellular annotation in their '
                      'dataset.'],
         'domain_of': ['Cell'],
         'examples': [{'value': 'Goblet cell'}, {'value': 'microglia'}]} })
    cell_type_ontology_term_id: Optional[str] = Field(default=None, title="Cell Type Ontology Term ID", description="""Cell Ontology (CL) term.

Use `cell_type_ontology_term_id` for integrated objects. `cell_type_ontology_term_id` will be required for submission to CELLxGENE.""", json_schema_extra = { "linkml_meta": {'alias': 'cell_type_ontology_term_id',
         'annotations': {'annDataLocation': {'tag': 'annDataLocation', 'value': 'obs'},
                         'cxg': {'tag': 'cxg', 'value': 'cell_type_ontology_term_id'},
                         'tier': {'tag': 'tier', 'value': 'Tier 1'}},
         'comments': ['Encoding of cell type to help alignment with other datasets.'],
         'domain_of': ['Cell'],
         'examples': [{'value': 'CL:0001204'}],
         'notes': ['This must be a Cell Ontology (CL) term '
                   '(https://www.ebi.ac.uk/ols4/ontologies/cl).\n'
                   '\n'
                   'If no appropriate high-level term can be found or the cell type is '
                   "unknown, then it is strongly recommended to use 'unknown'.\n"
                   '\n'
                   'The following terms must not be used: "CL:0000255" for eukaryotic '
                   'cell; "CL:0000257" for Eumycetozoan cell; "CL:0000548" for animal '
                   'cell.']} })


# Model rebuild
# see https://pydantic-docs.helpmanual.io/usage/models/#rebuilding-a-model
Dataset.model_rebuild()
AdiposeDataset.model_rebuild()
GeneticDiversityDonorTier2.model_rebuild()
GutDataset.model_rebuild()
Donor.model_rebuild()
Sample.model_rebuild()
AdiposeSample.model_rebuild()
GutSample.model_rebuild()
MusculoskeletalDataset.model_rebuild()
MusculoskeletalDonorTier2.model_rebuild()
MusculoskeletalSampleTier2.model_rebuild()
Cell.model_rebuild()

