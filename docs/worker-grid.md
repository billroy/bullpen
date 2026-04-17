This document lays out the evolution of the worker grid.

The objective of this task is to convert the fixed worker grid into a very large/unbounded array of workers that can extend indefinitely in rows and columns, like a spreadsheet.  For design purposes, think 20x20 for testing, 100x100 for soft max, 1000x1000 for minimum design max)

** Current status **
The worker grid layout is currently a fixed grid whose dimensions are chosen by the user from a dropdown in the header.  All layout computation flows from fitting a fixed number of rows and columns of worker cards into the viewport.  The cards are sized according to what will fit.  Changing the dimensions causes a rearrangement of the workers.

** Desired status **
The grid is indefinite in every direction.  The default layout is 4 rows by 5 columns with the Large card layout

Shift+Scrolling is used to scroll the grid into new territory
Shift+Dragging
  - this seems awkward, propose better UI mechanics for grid manipulation

Card layouts are chosen by the user using three icon-based pickers in the tab header. These control the amount of information shown in all the cards in the current worker pane.
- Small: just shows the header of the current card
  - Note: Move the worker status (IDLE, WORKING) to the header for all card sizes
- Medium: Header + task queue
- Large: Header + task queue + chat readout

** Keyboard controls and selection **
Add a way to select a worker card with the mouse by clicking.
When a card is selected the arrow keys move to another adjacent card, stopping at workspace edges
Move the empty worker card + menu to a ... menu like occupied worker cards have
  Unoccupied cards have a menu with Add Worker and Paste Worker
Add Copy Worker to occupied cards menu
Enter in a card slot brings up its menu; up/down/enter/escape allow navigation and commands from the menu
Support for multiple selection is deferred but coming; design for it.
