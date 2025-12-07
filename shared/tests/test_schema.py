"""
Test script for schema functionality.
"""
from hca_validation.schema_utils.schema_utils import schema_classes, load_schemaview
import hca_validation.schema.generated.core as schema

def test_schemaview_classes():
  """
  Test that all classes in the mapping exist in the schema when loaded as a schemaview.
  """
  schemaview = load_schemaview()
  print(schemaview)
  for classes in schema_classes.values():
    for class_name in classes.values():
      print(class_name)
      assert schemaview.get_class(class_name) is not None

def test_generated_classes():
  """
  Test that all classes in the mapping exist in the exported Pydantic schema.
  """
  for classes in schema_classes.values():
    for class_name in classes.values():
      assert hasattr(schema, class_name)
