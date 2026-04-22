"""Deployment config loader — load, cache, and expose user role helpers."""
from unittest.mock import patch
import pytest
from willow.fylgja.safety.deployment import (
    get_deployment_config,
    get_user_role,
    is_psr,
    training_allowed,
    DEFAULT_CONFIG,
)


def test_default_config_returned_when_store_empty():
    with patch("willow.fylgja.safety.deployment._load_from_store", return_value=None):
        config = get_deployment_config(refresh=True)
    assert config["training_opt_in"] is False
    assert config["training_child_opt_in"] is False


def test_config_loaded_from_store():
    stored = {**DEFAULT_CONFIG, "deployment_id": "sean-home", "psr_names": ["Ruby Campbell"]}
    with patch("willow.fylgja.safety.deployment._load_from_store", return_value=stored):
        config = get_deployment_config(refresh=True)
    assert config["deployment_id"] == "sean-home"
    assert "Ruby Campbell" in config["psr_names"]


def test_get_user_role_adult_when_no_profile():
    with patch("willow.fylgja.safety.deployment._load_user_profile", return_value=None):
        role = get_user_role("unknown_user")
    assert role == "adult"


def test_get_user_role_from_profile():
    profile = {"user_id": "ruby", "name": "Ruby Campbell", "role": "child"}
    with patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        role = get_user_role("ruby")
    assert role == "child"


def test_is_psr_true_when_in_psr_names():
    config = {**DEFAULT_CONFIG, "psr_names": ["Ruby Campbell", "Opal Campbell"]}
    profile = {"user_id": "ruby", "name": "Ruby Campbell", "role": "child"}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config), \
         patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        assert is_psr("ruby") is True


def test_is_psr_false_when_not_in_list():
    config = {**DEFAULT_CONFIG, "psr_names": ["Ruby Campbell"]}
    profile = {"user_id": "sean", "name": "Sean Campbell", "role": "adult"}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config), \
         patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        assert is_psr("sean") is False


def test_training_allowed_false_when_deployment_opt_in_off():
    config = {**DEFAULT_CONFIG, "training_opt_in": False}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config):
        assert training_allowed("sean", session_consent=True) is False


def test_training_allowed_true_when_opted_in_and_consented():
    config = {**DEFAULT_CONFIG, "training_opt_in": True}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config):
        assert training_allowed("sean", session_consent=True) is True


def test_training_not_allowed_without_session_consent():
    config = {**DEFAULT_CONFIG, "training_opt_in": True}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config):
        assert training_allowed("sean", session_consent=False) is False


def test_training_not_allowed_for_child_even_if_opted_in():
    config = {**DEFAULT_CONFIG, "training_opt_in": True, "training_child_opt_in": False}
    profile = {"user_id": "ruby", "name": "Ruby Campbell", "role": "child"}
    with patch("willow.fylgja.safety.deployment.get_deployment_config", return_value=config), \
         patch("willow.fylgja.safety.deployment._load_user_profile", return_value=profile):
        assert training_allowed("ruby", session_consent=True) is False
