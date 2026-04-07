### Bullpen Functional Spec ###

Bullpen is a somewhat opinionated agent orchestration framework targeted to software development and based on the metaphor of dispatching tasks to specialized workers organized into teams in bullpens similar to the cubicle bullpens to which human software developers are often relegated.

The Operator is the entity running a bullpen.  Initially assumed to be a human person.

The entities doing the work are known as Workers.  Each worker is represented by a card in the Bullpen display, which is shown as a grid of such Worker Cards.  Each card has a description of the job the worker does, like "Feature Architect" or "Code Reviewer" or "Plan Reviewer" or "Code Merger" or "Deployer".  These are set up when the worker profile is created.  24 worker profiles are supplied with the product as default examples.  Implementation note: generate a candidate list of 30 profiles related to software dev and devops and propose them for human pruning.

The Operator "hires" workers by configuring a worker slot in the bullpen from a menu or defining a new worker expertise prompt for a slot de novo.

The Operator assigns work to workers, several ways.  A worker can be configured to watch a queue in the kanban for new tasks and pick up the next task when it appears.  The Operator can drag one or more kanban task cards to a worker to add it to the workers internal task queue.

Workers operate on tasks in their queue one at a time.  They package the task request with their worker expertise and ship them off to their selected agent for processing.

On completion, or on an exception event, workers can move tasks from state to state, can hand them off to other workers as configured, and can hand them back to the Operator.  


## Left Pane ##




## Right Pane ##
The right pane has a tab selector which controls the pane contents.

# Kanban Tab  and Task Tickets #
The Kanban Tab is a kanban view of the files in the .bullpen/tasks folder in the database.
The files are .md files in beans format.  Each file represents a task.
It is intended that these files will be committed with the repo to memorialize issue status with each commit.
Each file holds an issue in a loosely standardized md format suitable for workflow tracking

# Workspace File Viewer and File Edit/Preview #
This tab allows the viewing of a tree view of the files, the selecting of a file to view open it, multiple files open in separate tabs.
Supports .txt and .md for editing, as many read-only view types as MacOS makes easy, but especially html, pdf, source code
Special support for source code limited to syntax highlighting.
Consider an open source edit/preview control for this section if possible rather than building it.

# Bullpen Tab #
The bullpen is a tab containing a collection of worker cards.
Each card represents a status and control surface for a configurable agent.
The cards are organized in a fixed array.  
- Default: 4 rows of 6 columns of cards.  
The card organization, as well as other basic parameters of the bullpen, can be controlled from the Bullpen Tab Header 
A new card is created by selecting a worker from the worker library and clicking the + next to it in the header
Cards can be dragged from slot to slot.


# Bullpen Tab Header controls #
- Rows/Columns: dropdown, defaults to 4 x 6, options up to 7 x 10
- Worker library selector
- Team library selector


# Worker Card #
Worker card header displays name in a box with background color based on agent selector, has pencil edit icon which brings up the worker card header with controls per below and a status pill that usually reads IDLE in small caps or WORKING while an agent is busy.  Additional statuses to come including BLOCKED.  While the agent is busy there is a red STOP icon displayed in the header too.

Controls for worker card header:
- Agent selector (Claude, Codex)
- Model selector (contents per agent)
- Activation criteria (on drop, on assignment, time-based, manual)
- Disposition (where to send the task when complete: another worker, back to inbox ) 
- Prompt editor, with current prompt text
- Worker type selector

The body of the  card has a list of the tasks assigned to this worker.  This list is a drop target for tasks from the kanban pane.
When a worker has a task, it assembles its worker prompt with the content of the task ticket, the content of the bullpen prompt, and the content of the workspace prompt and issues it as a command to the selected AI agent
Agents are called by running local CLI programs which are presumed to be on the local machine.
For starters, the agents are: Claude and Codex

The card looks sort of like a Monopoly deed card with the color-coded background for the header and the multi-line display in the body shown in black on white.  The corners should be rounded, though.


# Bullpen Persistence #

# Future Features #
- Operator Inbox
- 
- Workflow routing in the bullpen
- Team In A Can
- Select/copy/paste in the bullpen
-

## Architecture and Hygiene ##
- Python 3 + flask server
- Use socket.io for client-server comms; avoid REST endpoints except as needed for interoperability
- Single user multi web client via socket.io for first release
- No database - 100% file-based persistence
- Use vue.js 3 on client, shall not use React/GraphQL
- There shall never be any build steps
- There shall be test coverage checked in with every commit that affects behavior
