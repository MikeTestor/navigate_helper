# Evaluation, Manual updates and a new front end are deferred

Status: accepted (issue #44)

Three things are deliberately not part of the Source Code work, so that nobody builds them by accident or assumes they were forgotten.

- **Judging Answers.** Neither Manual Answers nor Code Answers are judged systematically yet. Code Answers are labelled unverified. Evaluation of both is its own later issue, built on the Evaluation Set, once everything else works. A seed of real questions from the `bfx14` chat, with the files that prove each answer and no customer data, is collected first.
- **Updating the Manual.** The long-term aim is a loop where the Manual is updated when the Manual Answer failed and the Code Answer was correct. It is not built, and the Manual is never flagged or changed automatically.
- **Front end.** Python stays the backend. Gradio stays until a real trigger arrives (End Users as Askers, login and roles, branding, embedding in Navigate, a richer citation or review UI). The likely path then is a thin streaming HTTP API (FastAPI) over `ask` with a React/Next.js front end. Until then, Code Search progress is a plain event stream that does not depend on Gradio, which keeps that move cheap.
