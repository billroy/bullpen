# Specification: Value Workers

## summary
- new type of worker
- Hosts a single key:value pair
- key is the name of the node
- value is a number or string or expression
- expressions recalculate
- workers can see and update values in the sheet via mcp
- workers can use values in prompts and command lines


## expressions

- excel - style expressions with the usual operators and functions
- add a function to return the value of a given cell (value(location), ...)
- define function suite
- expressions can refer to other cells by cell coordinate (A37) 
- expressions can refer to other cells by value cell name using the value function value("interest rate")
- issue: how to refer to cells by name when the name includes spaces
- 
- mcp to get/set value from worker (by cell address or name)

## recalculation

Whenever a value is changed, all values that depend on it update.
For the first proof of concept this can be a simple brute-force recomputation.
Future releases will want need to improve evaluation speed/scalability using dependency analysis and partial updates
Issue: loop detection/handling



## UI

- when on an empty cell, start typing alpha characters to start a value cell creation editor
- the full syntax of a cell is: [<label>:] <value>, in other words an optional label followed by a colon followed by a value
  - e.g., in cell A23 type: interest rate: 5.3%<enter> and you get a value cell with title "interest rate" and value 5.3%
  - the cell shows the result like this in the header: interest rate <flush right> 5.3%

## Consumers of value cell values
Value cell values should be templatable into any worker definition using standard {variable} interpolation.  In the example above, it should be possible to say {a23} or {interest rate} and have the appropriate number templated into the prompt (Ai worker) or the shell script (shell worker).


Another example: 

- issue: how to deal with blanks embedded in names.  make it just work.


## Deferred to future phase

### value cell types
- number
- string
- picklist (find a better name)

### UI adjustment of values
- when the row height is bigger than minimum, show adjustment UI appropriate for the value type and the actual value
  - for numeric values: show a slider to increase/decrease through a relevant range (feature: auto range set)
  - for picklist values: show the pick list and allow choosing one
  - in number and string cases, show the value as a clickable for direct edit
