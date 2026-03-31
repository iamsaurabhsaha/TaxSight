"""Tests for document schemas."""


from ai_tax_prep.documents.schemas import (
    DOC_TYPE_NAMES,
    DOC_TYPE_SCHEMAS,
    Form1099B,
    Form1099DIV,
    Form1099INT,
    Form1099NEC,
    W2Data,
)


class TestW2Data:
    def test_defaults(self):
        w2 = W2Data()
        assert w2.wages == 0.0
        assert w2.employer_name == ""

    def test_with_data(self):
        w2 = W2Data(
            employer_name="Test Corp",
            wages=85000,
            federal_withholding=12000,
            state="CA",
            state_tax=4500,
        )
        assert w2.employer_name == "Test Corp"
        assert w2.wages == 85000

    def test_serialization(self):
        w2 = W2Data(wages=50000)
        data = w2.model_dump()
        assert data["wages"] == 50000
        restored = W2Data.model_validate(data)
        assert restored.wages == 50000


class TestForm1099NEC:
    def test_basic(self):
        nec = Form1099NEC(payer_name="Client Inc", nonemployee_compensation=25000)
        assert nec.nonemployee_compensation == 25000


class TestForm1099INT:
    def test_basic(self):
        f = Form1099INT(payer_name="Bank", interest_income=1500)
        assert f.interest_income == 1500


class TestForm1099DIV:
    def test_qualified_vs_ordinary(self):
        f = Form1099DIV(ordinary_dividends=5000, qualified_dividends=3000)
        assert f.ordinary_dividends == 5000
        assert f.qualified_dividends == 3000


class TestForm1099B:
    def test_gain(self):
        f = Form1099B(proceeds=15000, cost_basis=10000)
        assert f.proceeds == 15000
        assert f.cost_basis == 10000


class TestDocTypeRegistries:
    def test_schemas_complete(self):
        expected = {"w2", "1099_nec", "1099_int", "1099_div", "1099_b", "1099_r", "1098_e"}
        assert set(DOC_TYPE_SCHEMAS.keys()) == expected

    def test_names_complete(self):
        # Names includes consolidated_1099 which has no schema (uses custom extraction)
        for key in DOC_TYPE_SCHEMAS:
            assert key in DOC_TYPE_NAMES, f"{key} missing from DOC_TYPE_NAMES"
        assert "consolidated_1099" in DOC_TYPE_NAMES

    def test_all_schemas_are_pydantic(self):
        for name, schema in DOC_TYPE_SCHEMAS.items():
            instance = schema()
            assert hasattr(instance, "model_dump"), f"{name} schema is not a Pydantic model"
