from pydantic import BaseModel, Field


class JiraStoryCreate(BaseModel):
    summary: str = Field(..., description="Summary of the user story")
    description: str = Field("", description="Description of the user story")


class JiraStoryUpdate(BaseModel):
    summary: str | None = Field(None, description="Updated summary of the user story")
    description: str | None = Field(None, description="Updated description of the user story")
