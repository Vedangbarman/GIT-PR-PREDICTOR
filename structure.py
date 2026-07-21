from typing import Optional
from pydantic import BaseModel


class api_structure(BaseModel):
    owner: str
    name: str
    checkpoint_day: int
    days_elapsed: int
    additions: int
    deletions: int
    changed_files: int
    title_length: int
    author_login: str
    author_type: str
    num_labels: int
    created_dow: int
    created_hour: int
    comments_so_far: int
    reviews_so_far: int
    reviewer_assigned: int
    first_response_hours: float
    additions_norm: float
    deletions_norm: float
    changed_files_norm: float
    has_response_yet: int
    repo_key: str
    author_prior_pr_count: int
    author_prior_merge_rate: Optional[float] = None
    is_first_time_contributor: int
    repo_prior_pr_count: int
    repo_prior_merge_rate: Optional[float] = None
    created_at_day: int
    created_at_month: int