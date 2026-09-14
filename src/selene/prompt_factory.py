import os

from selene.config.selene_config import SelenePaths
from selene.constants import PROMPT_TEMPLATES_DIR_INTERNAL
from selene.generated.generated_prompt_factory import PromptFactory


class SelenePromptFactory(PromptFactory):
    """
    A class for retrieving and rendering prompt templates and prompt lists.
    """

    def __init__(self) -> None:
        user_templates_dir = SelenePaths().user_prompt_templates_dir
        os.makedirs(user_templates_dir, exist_ok=True)
        super().__init__(prompts_dir=[user_templates_dir, PROMPT_TEMPLATES_DIR_INTERNAL])
