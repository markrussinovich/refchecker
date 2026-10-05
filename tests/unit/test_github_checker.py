import base64
from unittest.mock import MagicMock, patch

from refchecker.checkers.github_checker import GitHubChecker


def test_github_owner_url_verifies_as_github_source():
    checker = GitHubChecker()
    reference = {
        'title': 'Qwen-vl 2.5 32b instruct',
        'authors': ['Alibaba DAMO Academy'],
        'venue': 'Qwen2.5-VL',
        'year': 2025,
        'url': 'https://github.com/QwenLM/',
    }

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        'login': 'QwenLM',
        'name': 'QwenLM',
        'company': 'Alibaba Cloud',
        'bio': 'Qwen large language model and multimodal model releases',
        'type': 'Organization',
        'created_at': '2023-01-01T00:00:00Z',
        'public_repos': 20,
    }

    with patch('refchecker.checkers.github_checker.requests.get', return_value=response) as mock_get:
        verified_data, errors, url = checker.verify_reference(reference)

    assert verified_data is not None
    assert verified_data['_matched_database'] == 'GitHub'
    assert verified_data['venue'] == 'GitHub Organization'
    assert errors == []
    assert url == 'https://github.com/QwenLM/'
    mock_get.assert_called_once()
    assert mock_get.call_args.args[0] == 'https://api.github.com/users/QwenLM'


def test_github_owner_url_404_is_unverified():
    checker = GitHubChecker()
    response = MagicMock()
    response.status_code = 404

    with patch('refchecker.checkers.github_checker.requests.get', return_value=response):
        verified_data, errors, url = checker.verify_reference({'url': 'https://github.com/not-a-real-owner/'})

    assert verified_data is None
    assert errors[0]['error_type'] == 'unverified'
    assert 'owner or organization not found' in errors[0]['error_details'].lower()
    assert url == 'https://github.com/not-a-real-owner/'


def test_github_blob_verifies_the_cited_file_not_repository_metadata():
    checker = GitHubChecker()
    url = 'https://github.com/meta-llama/llama3/blob/main/MODEL_CARD.md'
    reference = {
        'title': 'Llama 3 Model Card',
        'authors': ['AI@Meta'],
        'year': 2024,
        'url': url,
    }

    repo_response = MagicMock()
    repo_response.status_code = 200
    repo_response.json.return_value = {
        'name': 'llama3',
        'description': 'The official Meta Llama 3 GitHub site',
        'owner': {'login': 'meta-llama', 'name': 'Meta Llama'},
        'created_at': '2024-04-18T00:00:00Z',
        'archived': True,
    }
    file_response = MagicMock()
    file_response.status_code = 200
    file_response.json.return_value = {
        'name': 'MODEL_CARD.md',
        'path': 'MODEL_CARD.md',
        'html_url': url,
        'encoding': 'base64',
        'content': base64.b64encode(
            b'## Model Details\nMeta developed and released the Meta Llama 3 family.'
        ).decode('ascii'),
    }

    with patch(
        'refchecker.checkers.github_checker.requests.get',
        side_effect=[repo_response, file_response],
    ) as mock_get:
        verified_data, errors, verified_url = checker.verify_reference(reference)

    assert verified_data is not None
    assert verified_data['_matched_database'] == 'GitHub File'
    assert errors == []
    assert verified_url == url
    assert mock_get.call_args_list[1].args[0].endswith(
        '/repos/meta-llama/llama3/contents/MODEL_CARD.md'
    )
    assert mock_get.call_args_list[1].kwargs['params'] == {'ref': 'main'}


def test_github_blob_404_is_unverified():
    checker = GitHubChecker()
    url = 'https://github.com/meta-llama/llama3/blob/main/MISSING.md'
    repo_response = MagicMock()
    repo_response.status_code = 200
    repo_response.json.return_value = {
        'name': 'llama3',
        'description': 'The official Meta Llama 3 GitHub site',
        'owner': {'login': 'meta-llama', 'name': 'Meta Llama'},
        'created_at': '2024-04-18T00:00:00Z',
        'archived': False,
    }
    file_response = MagicMock()
    file_response.status_code = 404

    with patch(
        'refchecker.checkers.github_checker.requests.get',
        side_effect=[repo_response, file_response],
    ):
        verified_data, errors, verified_url = checker.verify_reference({
            'title': 'Missing file',
            'authors': ['AI@Meta'],
            'year': 2024,
            'url': url,
        })

    assert verified_data is None
    assert errors[0]['error_type'] == 'unverified'
    assert verified_url == url
