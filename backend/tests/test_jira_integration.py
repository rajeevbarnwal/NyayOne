from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@patch("app.integrations.jira.JiraClient.get_stories", new_callable=AsyncMock)
def test_get_stories(mock_get_stories):
    mock_get_stories.return_value = [
        {
            "id": "10001",
            "key": "SAATHI-1",
            "fields": {
                "summary": "Mock Story 1",
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "This is a mock description",
                                }
                            ]
                        }
                    ]
                },
                "status": {"name": "In Progress"},
            },
        }
    ]

    response = client.get("/api/v1/integrations/jira/stories")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["key"] == "SAATHI-1"
    assert data[0]["fields"]["summary"] == "Mock Story 1"
    mock_get_stories.assert_called_once()


@patch("app.integrations.jira.JiraClient.create_story", new_callable=AsyncMock)
def test_create_story(mock_create_story):
    mock_create_story.return_value = {"id": "10002", "key": "SAATHI-2"}

    payload = {"summary": "New Story", "description": "Story Description"}
    response = client.post("/api/v1/integrations/jira/stories", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["key"] == "SAATHI-2"
    mock_create_story.assert_called_once_with(
        summary="New Story", description="Story Description"
    )


@patch("app.integrations.jira.JiraClient.update_story", new_callable=AsyncMock)
def test_update_story(mock_update_story):
    response = client.put(
        "/api/v1/integrations/jira/stories/SAATHI-2",
        json={"summary": "Updated Story", "description": "Updated Description"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    mock_update_story.assert_called_once_with(
        issue_key="SAATHI-2",
        summary="Updated Story",
        description="Updated Description",
    )
