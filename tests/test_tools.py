import pytest
from unittest.mock import patch

from src.tools.biophys_tool import calc_biophysics, BioPhysInput
from src.guards.petase_validator import PetaseValidator

def test_biophys_valid():
    """Deterministic assertion: II calculation works, MW >0"""
    seq = "MNFPRASRLMQAVTDAA" * 15
    out = calc_biophysics(BioPhysInput(sequence=seq))
    assert out.molecular_weight > 0
    assert out.ii is not None
    print(f"II={out.ii}")

def test_biophys_ii_stable():
    """Outcome assertion: II<40 stable per BioPython Guruprasad"""
    seq = "MNFPRASRLMSVNVDEKKLAEVGLESDEDIDISTLNYEKTETVLRDSAIDCRICDEEFSDRINLLRHITSHGLVNPHICEVCSKNFTSKLSLRIHMLRHNGIHECGECSKIFTKKTSLLLHMRTHTDNRPYSCSKCGKSFSTGANLRKHLKFLHTGEKPYICEICNKSFTLKSNLRNHMKHHTGEKPFSCSHCGKSFIQKSDLRKHLKTHTGEEQYRCMICSKSFAQSSNLKRHMRIHTGEKPYSCSHCSKAFSTGADLRRHMRIHTGEKPYSCSHCGKSFSQKSNLRRH"
    # Historical sequence fixture; instability alone does not establish function.
    out = calc_biophysics(BioPhysInput(sequence=seq))
    assert out.ii < 40, f"Expected stable II<40, got {out.ii}"
    assert out.ii == pytest.approx(38.16, abs=0.5)

def test_validator_length_fail():
    """Input guard: length 240-320 enforced"""
    with pytest.raises(Exception):
        PetaseValidator(sequence="AAA") # Too short, should fail
    with pytest.raises(Exception):
        PetaseValidator(sequence="A" * 400) # Too long

def test_validator_invalid_aa():
    """Output guard: canonical AA only, no B/J/O/U/X/Z"""
    with pytest.raises(Exception):
        PetaseValidator(sequence="A" * 289 + "X") # X non-canonical
    with pytest.raises(Exception):
        PetaseValidator(sequence="A" * 289 + "B") # B non-canonical

def test_validator_ok():
    """Happy path: valid 290 AA passes all guards"""
    v = PetaseValidator(sequence="MNFPRASRLM" * 29) # 290 AA canonical
    assert v.sequence
    assert len(v.sequence) == 290

def test_esmfold_unavailable_on_504():
    """An exhausted folding service supplies no measurement or synthetic success."""
    # Mock ESMFold tool to simulate 504
    from src.tools.esmfold_tool import esmfold_fold

    with patch('src.tools.esmfold_tool.requests.post') as mock_post, patch('src.tools.esmfold_tool.time.sleep') as sleep:
        mock_post.return_value.status_code = 504
        mock_post.return_value.raise_for_status.side_effect = Exception("504 Gateway Timeout")

        # Service failure remains explicit.
        result = esmfold_fold("MNFPRASRLM" * 29)
        assert result['plddt'] is None
        assert result['success'] is False
        assert result['status'] == 'unavailable'
        assert result['attempts'] == mock_post.call_count == 3
        assert sleep.call_count == 2

def test_length_enforcement_121_to_290():
    """Short generations are rejected, not padded into apparent candidates."""
    from src.agents.designer_agent import validate_generated_sequence
    with pytest.raises(ValueError, match="length"):
        validate_generated_sequence("MNFPRASRLM" * 12 + "A")
