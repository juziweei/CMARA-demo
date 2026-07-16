# 14 · Frontend Redesign and English Scenario Dataset Plan

> This document is the working plan for the next phase of the demo.
> It turns the current debug-style page into a presentation-ready cockpit, and it defines the English scenario library that will drive the whole experience.

---

## 1. Why this needs a separate plan

The current front end proves the backend loop, but it does not yet prove the product story.

What we need to show is not just:

- API is reachable
- a request returns
- a trace exists

What we need to show is:

- the system remembers over time
- the system knows when not to act
- the system asks the smallest useful clarifying question
- the system learns from the answer
- the same logic works across multiple vehicle scenarios

This means the next step is not a cosmetic refresh. It is a redesign of the presentation layer and the demo dataset together.

---

## 2. Target experience

The audience should feel they are watching a vehicle memory agent, not a developer console.

The page should answer five questions immediately:

1. What scenario am I looking at?
2. What does the system already remember?
3. What is missing or ambiguous right now?
4. Why did it ASK or ACT?
5. What did it learn that will help next time?

If a viewer can answer those five questions without reading raw JSON first, the redesign is working.

---

## 3. New information architecture

The new page should be organized into four visible layers.

### 3.1 Scenario Gallery

This is the top-level chooser.

It should show:

- scenario title
- short description
- what the scenario demonstrates
- current stage in the demo
- whether it is a first-time run or a reuse run

The gallery is not just navigation. It is part of the narrative.

### 3.2 Conversation Theater

This is the main center panel.

It should present:

- long English user turns
- assistant responses
- clarification questions
- auto-play or manual step-through
- highlighted moments when the system asks or learns

This area should feel like a live demo, not a chat log.

### 3.3 Memory Timeline

This panel shows how memory changes over time.

It should make the following visible:

- direct user-stated preferences
- offline summary preferences
- learned-from-clarification preferences
- active vs expired status
- source evidence

This is where the audience sees that the system remembers more than the current prompt.

### 3.4 Decision Flow

This panel explains the policy step.

It should show a short human-readable flow:

```text
context -> retrieved memories -> missing dimension -> decision -> tool -> update
```

The raw JSON trace can still exist, but it should be secondary and collapsible.

---

## 4. Phased delivery plan

### Phase 1: Narrative lock

Goal:

- freeze the demo story
- freeze the terminology
- freeze the layout skeleton

Deliverables:

- one-page demo narrative
- three talk tracks: technical, paper, investor
- one scenario flow for the live demo

Done when:

- everyone describes the demo the same way
- the front end can be built without changing the story again

### Phase 2: English scenario library

Goal:

- build a reusable library of long English scenarios
- cover different vehicle memory behaviors

Deliverables:

- at least 5 scenario packs
- each pack includes long user turns, clarifications, learning steps, and reuse turns
- each pack can be replayed deterministically

Done when:

- the demo can switch scenarios without changing backend code
- each scenario shows a different kind of memory behavior

### Phase 3: UI redesign

Goal:

- replace the debug layout with a presentation cockpit

Deliverables:

- scenario selector
- conversation theater
- memory timeline
- decision flow view
- compact developer trace drawer

Done when:

- the page looks like a demo product
- the key logic can be understood at a glance

### Phase 4: Presentation hardening

Goal:

- make the page stable in a live room

Deliverables:

- autoplay mode
- manual step mode
- reset and replay
- short live-demo buttons
- predictable scroll behavior

Done when:

- we can run the whole demo twice in a row without manual cleanup

---

## 5. English dataset rules

The dataset must be English only.

The reason is simple:

- it is easier to present to a mixed audience
- it feels more like a real vehicle assistant
- long English turns make the context more natural
- it avoids short-script demo behavior

Hard rules:

1. Every user turn should sound like spoken English, not a label.
2. Every turn should be long enough to carry context.
3. Every scenario should include at least one ambiguous or conflicting condition.
4. Every scenario should include at least one clarification question.
5. Every scenario should include at least one learned preference.
6. Every scenario should include at least one future reuse turn.
7. Every scenario should include at least one offline summary event where relevant.

Style rule:

- Prefer natural, high-context, vehicle-like speech.
- Avoid robotic phrasing.
- Avoid short fragments like "family trip hot".

---

## 6. Scenario data shape

Each scenario should be represented as a structured record.

Recommended fields:

```json
{
  "id": "family_coastal_trip",
  "title": "Family Coastal Trip",
  "theme": "family comfort",
  "demo_goal": "show quiet cabin preference, health-dependent AC preference, and reuse after clarification",
  "memory_dimensions": ["family_context", "child_sleep", "health_state", "temperature", "music", "privacy"],
  "required_events": ["seed", "ask", "clarification", "learn", "summarize", "reuse"],
  "turns": [],
  "visual_emphasis": ["memory timeline", "decision flow", "reused preference badge"]
}
```

This shape is small enough for a JS file, JSON file, or backend fixture.

---

## 7. Scenario catalog

### 7.1 Family Coastal Trip

What it demonstrates:

- quiet cabin preference
- child sleeping in the back seat
- health-dependent temperature preference
- clarification learning
- reuse after learning

Memory dimensions:

- family trip
- child sleep state
- health state
- cabin temperature
- music / cabin quietness

Sample opening:

```text
We are driving to the coast this Saturday with my wife and our daughter, and I want the cabin to stay calm because she usually falls asleep after about twenty minutes. Please keep the music low, avoid unnecessary voice prompts, and do not make sudden route announcements unless something important changes.
```

Sample clarification:

```text
I am feeling a lot better today, but I would still prefer the cabin to be only moderately cool so that my daughter stays comfortable in the back seat.
```

Reuse turn:

```text
We are going on another family outing this weekend, and the weather looks warm again, but this time I have fully recovered, so you can cool the cabin normally while still keeping the back seat quiet.
```

### 7.2 Morning Commute Under Time Pressure

What it demonstrates:

- route preference changes under time pressure
- short window for action
- direct ACT when the condition is clear
- ASK when route priority is unclear

Memory dimensions:

- commute
- time pressure
- fastest route
- toll road tolerance
- notification handling

Sample opening:

```text
I am leaving for work a bit later than usual, and I have an important meeting at nine, so I need the fastest reliable route even if it is slightly longer in distance. If there is heavy traffic, I want you to prioritize arrival time over scenic or quieter roads.
```

Sample clarification:

```text
If the traffic forecast becomes unpredictable, you should ask me whether I am still willing to pay a toll to save ten or fifteen minutes, because today I care more about being on time than saving the fee.
```

Reuse turn:

```text
I have the same meeting schedule again this week, and I am already running late, so please use the fastest route without asking me again about tolls unless the situation has changed materially.
```

### 7.3 Elderly Passenger Comfort

What it demonstrates:

- passenger comfort preference
- multi-person conflict
- more conservative climate and volume choices
- memory of a passenger-specific condition

Memory dimensions:

- elderly passenger
- back seat comfort
- temperature
- seat position
- audio volume

Sample opening:

```text
My parents are riding with us today, and my father gets cold easily while my mother gets uncomfortable if the air is too strong on her face. Please make the cabin softer than usual, keep the fan away from the back seat, and avoid sudden changes in volume.
```

Sample clarification:

```text
If my father says he feels chilly again, please ask whether he wants the airflow reduced or the temperature raised, because he usually prefers a small change rather than a big one.
```

Reuse turn:

```text
They are coming with us again tomorrow, and you already know that the back seat should stay gentle and quiet, so keep the same comfort profile unless I tell you otherwise.
```

### 7.4 EV Range Anxiety Trip

What it demonstrates:

- route and charging preference
- battery-aware decision making
- tradeoff between fast arrival and charging safety
- explicit request for clarification when range is uncertain

Memory dimensions:

- battery level
- charging stop preference
- route risk
- arrival time
- charger reliability

Sample opening:

```text
We are taking the electric car on a longer trip today, and I want you to keep an eye on the battery reserve because I do not want to arrive with almost no margin left. If the route becomes tight, please favor reliable charging stops over the absolute fastest path.
```

Sample clarification:

```text
If the estimated range drops below the safe threshold, ask me whether I prefer a shorter charging stop or a safer charging stop with a more reliable station, because I do not want to make a bad decision under pressure.
```

Reuse turn:

```text
We are taking the same highway next week, and now that you remember I prefer reliable charging over risky shortcuts, you can plan the route with that in mind from the start.
```

### 7.5 Work Call Privacy Mode

What it demonstrates:

- privacy-sensitive cabin behavior
- notification suppression
- music and volume preferences
- direct reuse of a known work mode

Memory dimensions:

- work call
- privacy
- notification handling
- volume
- ambient distractions

Sample opening:

```text
I have a client call in ten minutes, and I need the car to behave like a quiet office on wheels. Please mute nonessential notifications, keep the music off, and make sure the cabin does not interrupt me with anything noisy or unnecessary.
```

Sample clarification:

```text
If a navigation prompt is truly important during the call, ask me once before repeating it, because I can handle a single interruption but not a stream of them.
```

Reuse turn:

```text
I am in the same kind of meeting again this afternoon, and you already know that this means silent mode, no music, and minimal interruptions unless the route changes in a way that really matters.
```

### 7.6 Night Drive Fatigue Management

What it demonstrates:

- fatigue-aware driving assistance
- more cautious prompts
- cabin lighting and alertness tradeoff
- learning from a prior clarification

Memory dimensions:

- fatigue
- night driving
- cabin brightness
- alertness
- drive mode

Sample opening:

```text
It is late and I have been driving for hours, so I want the cabin to feel calm and focused. Please keep the lights low, avoid playful prompts, and if you think I sound tired, ask me once whether I want a more alert driving setup.
```

Sample clarification:

```text
I am not dangerously tired, but I do want a slightly more alert cabin now, with a bit more light and a more attentive tone from the assistant.
```

Reuse turn:

```text
You already asked me about this last time, and now you know that late-night driving usually means a calm cabin first, then a brief alertness check if I seem tired.
```

---

## 8. How the UI should present each scenario

Each scenario page should have its own emphasis.

### Family Coastal Trip

Show:

- child sleep state
- health state
- temperature preference conflict
- learned preference badge

### Morning Commute Under Time Pressure

Show:

- route decision
- arrival time pressure
- toll tradeoff
- direct ACT when the condition is clear

### Elderly Passenger Comfort

Show:

- passenger-specific memory
- softer cabin setting
- multi-person comfort balance

### EV Range Anxiety Trip

Show:

- range estimate
- charger reliability
- route confidence

### Work Call Privacy Mode

Show:

- silence mode
- notification suppression
- privacy-sensitive assistant behavior

### Night Drive Fatigue Management

Show:

- alertness state
- calmer assistant behavior
- subtle intervention rather than noise

---

## 9. Internal logic visualization

Do not show raw trace JSON as the primary explanation.

Instead, show a readable flow:

1. Context parsing
2. Memory retrieval
3. Missing dimension detection
4. Policy decision
5. Tool execution or clarification
6. Memory update
7. Future reuse

Recommended visual labels:

- `Context`
- `Retrieved Memories`
- `Missing Dimension`
- `Decision`
- `Action`
- `Update`
- `Reuse`

Recommended status tags:

- `active`
- `expired`
- `learned`
- `needs_clarification`
- `reused`

---

## 10. Delivery sequence

The implementation should happen in this order:

1. Add the scenario data structure.
2. Add the first five English scenario packs.
3. Redesign the page layout.
4. Replace the debug trace emphasis with a memory/decision story.
5. Keep the raw JSON in a collapsible developer drawer.
6. Add autoplay and manual step mode.
7. Stabilize for live demo.

---

## 11. Success criteria

This phase is done when:

1. The page can present multiple scenarios.
2. Every scenario uses long English conversation.
3. Every scenario shows memory, ambiguity, decision, and reuse.
4. The page looks like a presentation product rather than a debugging surface.
5. The structure is clear enough for technical review, paper discussion, and investor communication.

