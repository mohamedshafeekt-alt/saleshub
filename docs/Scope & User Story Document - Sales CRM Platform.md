# Scope & User Story Document - Sales CRM Platform

## Scope & User Story Document
### Sales Prospecting & CRM Platform

**Prepared by:** Ram Prakash (Business Analyst)
**Source Documents:** BRD (Client), HubSpot Contact Export, InnoBoon Pre-Sales Checklist Template
**Status:** Draft — for internal review before client walkthrough
**Version:** 1.0

---

## 1. Purpose

This document consolidates all functional requirements into a single reference covering every feature, screen, UI element, and user story required to build the Sales Prospecting & CRM Platform. It incorporates the detailed Pre-Sales Checklist structure shared by the client (InnoBoon template) into the platform's functional design.

---

## 2. User Roles

| Role | Description |
|---|---|
| Sales Rep | Manages leads, accounts, deals, and pre-sales checklist items tagged "Sales" |
| Delivery / Technical SME | Owns checklist items tagged "Delivery" — solutioning, estimation, technical validation |
| Sales Manager / Director | Read/oversight access across all deals, accounts, dashboards; reassigns ownership |
| Joint (Shared Responsibility) | Not a separate login role — represents checklist items requiring both Sales and Delivery sign-off |

---

## 3. Screens — Full List

1. Login Screen
2. Dashboard / Home Screen
3. Leads List Screen
4. Lead Detail / Create-Edit Screen
5. Accounts List Screen
6. Account Detail Screen (tabbed: Contacts, Deals, Checklist, Documents, Activity)
7. Deals / Pipeline Board Screen
8. Deal Detail Screen
9. Pre-Sales Checklist Screen
10. Tasks Screen
11. Notifications Center
12. Sales Performance Dashboard
13. Staff Augmentation — Resource List Screen
14. Staff Augmentation — Opportunity Tracking Screen
15. Documents & Proposals Screen
16. Activity Log / Timeline Screen
17. Settings / User Management Screen (Admin)

---

## 4. Detailed Feature, Screen & User Story Breakdown

### 4.1 Login Screen

**Elements:** Email field, password field (show/hide toggle), Remember Me checkbox, Forgot Password link, Login button, error banner.

**Functionality:** Authenticates user, routes to Dashboard on success.

**User Stories**
- As a Sales Rep, I want to log in securely so that only authorized users access client and deal data.
- As a user, I want a "Forgot Password" option so I can regain access without IT intervention.

### 4.2 Dashboard / Home Screen

**Elements:** "+ New Lead" CTA, Recent Leads/Accounts list, quick stats strip, notifications bell icon.

**Functionality:** Landing page after login; entry point to all modules.

**User Stories**
- As a Sales Rep, I want to see my recent leads and deals immediately after login so I can resume work quickly.
- As a Sales Manager, I want a snapshot of team activity on the dashboard so I don't need to open reports separately.

### 4.3 Leads List Screen

**Elements:** Table/list of leads (Name, Company, Owner, Source, Tier, Status), filter bar (owner, source, tier, status), search box, "+ New Lead" button, bulk import button.

**Functionality:** View, filter, search, and manage all leads; entry point for bulk HubSpot import.

**User Stories**
- As a Sales Rep, I want to filter leads by tier (Diamond/Gold/Silver/Bronze) so I can prioritize high-value follow-ups.
- As a Sales Rep, I want to search leads by company name or owner so I can find a specific lead quickly.
- As a Sales Manager, I want to bulk-import existing HubSpot leads so historical data isn't lost.

### 4.4 Lead Detail / Create-Edit Screen

**Elements:** Fields for Name, Company, Domain, Job Title, Email(s), Phone, Source (dropdown), Owner (dropdown), Tier (dropdown), Status, Save/Cancel buttons, "Convert to Account" button.

**Functionality:** Create or edit lead details; convert qualifying leads into Accounts.

**User Stories**
- As a Sales Rep, I want to tag a lead's source and owner at creation so tracking and accountability start immediately.
- As a Sales Rep, I want to convert a qualified lead into an Account so I can begin building the deal relationship.
- As a Sales Rep, I want duplicate-email detection when creating a lead so I don't create redundant records.

### 4.5 Accounts List Screen

**Elements:** Table of accounts (Company, Domain, Tier, Primary Owner, # of Deals), filter bar, search box.

**Functionality:** Central view of all client accounts.

**User Stories**
- As a Sales Rep, I want to see all accounts I own in one list so I can manage my portfolio.
- As a Sales Manager, I want to see accounts across the whole team so I have full visibility.

### 4.6 Account Detail Screen (Tabbed View)

**Elements:** Header (Company Name, Tier, Owner); Tabs — Contacts, Deals, Pre-Sales Checklist, Documents, Activity.

**Functionality:** Single rollup view of everything tied to an account.

**User Stories**
- As a Sales Rep, I want to see all contacts, deals, and documents for an account in one place so I don't switch screens constantly.
- As a Sales Manager, I want to open any account and see its full history so I can step in without a handover call.

### 4.7 Deals / Pipeline Board Screen

**Elements:** Kanban-style board with columns for each stage (Qualification, Evaluating, Negotiating, Contracting, Closed Won, Closed Lost, Cold), deal cards showing value and owner, drag-and-drop between stages.

**Functionality:** Visual pipeline management.

**User Stories**
- As a Sales Rep, I want to drag a deal card to the next stage so pipeline status stays current with minimal effort.
- As a Sales Manager, I want a board view of all deals by stage so I can spot bottlenecks at a glance.
- As a Sales Rep, I want to mark a deal "Cold" with a reason so we retain insight into why it stalled.

### 4.8 Deal Detail Screen

**Elements:** Deal Name, Associated Account, Value, Currency, Expected/Actual Close Date, Payment Status, Owner, Stakeholders list, stage history log.

**Functionality:** Full deal record management.

**User Stories**
- As a Sales Rep, I want to log multiple stakeholders on a deal so I capture everyone influencing the decision.
- As a Sales Manager, I want to see a deal's full stage-change history so I understand how it progressed (or stalled).

### 4.9 Pre-Sales Checklist Screen

*(Built directly from the InnoBoon Pre-Sales Checklist Template)*

**Elements:** Stage tabs or accordion (Stage 1–5), checklist rows per item with: Item description, Owning team (Sales/Delivery/Joint), Status toggle (Open/Completed), Notes/Details field, overall stage completion indicator.

**Functionality — mapped stage by stage:**

- **Stage 1 – Lead Qualification (Sales):** Client company profile, industry & business model, geography, CRM entry, decision maker & influencers identified, budget capability check, proposal process identified, problem statement documented, new vs. replacement initiative, competitor pitch identification, timeline/priority, InnoBoon-fit check, deal size worth pursuing, competitive landscape, Go/No-Go decision, qualified opportunity confirmation.

- **Stage 2 – Client Meeting Preparation (Sales/Delivery):** Meeting objective, agenda shared, attendees confirmed, past interactions reviewed, discovery questions prepared, expected outcome defined, technical SMEs identified, client background & offerings reviewed (mandatory pre-meeting), case studies/references reviewed, solution scenarios considered, risk areas & effort gut-check (conditional on RFP availability), clarification questions prepared.

- **Stage 3 – Post-Meeting, Solution & Estimation (Sales/Delivery):** MOM prepared within 24 hours, problem statement validated, scope boundaries documented, budget signals reconfirmed, proposal deadline confirmed, Sales-Delivery syncup (mandatory), functional/non-functional requirements documented, integrations identified, assumptions & dependencies listed, architecture diagram (conditional on client potential), tech stack finalized, environment/security/compliance considerations (need-basis), WBS created, effort estimation, resource plan, timeline, risks & mitigation, costing shared with Sales (on client request).

- **Stage 4 – Execution Approach Review:** Presentation preparation covering execution approach and proposed solution approach for client walkthrough.

- **Stage 5 – Proposal Review, Technical Validation & Final Sending:** Pricing strategy, margin validation, payment milestones, optional AMC, client-focused problem-based proposal, ROI positioning, differentiators, case study alignment; technical validation — scope clarity, no ambiguity in deliverables, explicit assumptions/out-of-scope, realistic timeline, resource availability, risk factors, change request mechanism; final sending — version control, client details verification, attachments, NDA compliance, submission format, submission confirmation, follow-up meeting scheduled.

**User Stories**
- As a Sales Rep, I want a stage-wise checklist tied to each account/deal so nothing gets missed before a proposal goes out.
- As a Delivery SME, I want my checklist items (e.g., WBS, effort estimation, tech stack) clearly separated from Sales items so ownership is unambiguous.
- As a Sales Manager, I want to see which checklist item caused a delay so I can address accountability gaps.
- As a Sales Rep, I want conditional checklist items (e.g., "architecture diagram — only if client is highly potential") to be visibly flagged as optional so the checklist doesn't feel rigid for smaller deals.
- As a Delivery SME, I want to add notes to a checklist item (e.g., "if RFP provided, this can be checked") so context isn't lost between handoffs.

### 4.10 Tasks Screen

**Elements:** My Tasks / Team Tasks toggle, task cards (title, due date, priority, linked deal/lead), overdue flag, "+ New Task" button.

**Functionality:** Personal and team task visibility, auto-generated from stage transitions or checklist items.

**User Stories**
- As a Sales Rep, I want tasks auto-created when a deal moves stages so I don't have to manually track next steps.
- As a Sales Manager, I want to see overdue tasks across the team so I can intervene before deals stall.

### 4.11 Notifications Center

**Elements:** Notification list (task assigned, overdue, stage transition, follow-up due), read/unread indicator, notification settings link.

**Functionality:** In-app alerts; optional email mirroring.

**User Stories**
- As a Sales Rep, I want an in-app alert when a task is overdue so I don't miss follow-ups.
- As a user, I want to control which notifications also come via email so I'm not overwhelmed.

### 4.12 Sales Performance Dashboard

**Elements:** Metric tiles (leads generated, Leads to Accounts, meetings, proposals sent, closures), funnel chart, Target vs. Actual chart, filters (date range, owner, tier).

**Functionality:** Reporting and performance tracking.

**User Stories**
- As a Sales Manager, I want a conversion funnel view so I can identify which stage loses the most deals.
- As a Sales Rep, I want to see my individual performance vs. target so I can track my own progress.
- As a Director, I want to filter dashboards by date range and rep so I can prepare for review meetings.

### 4.13 Staff Augmentation — Resource List Screen

**Elements:** Resource table (Name, Skill, Availability, Current Allocation), filter by skill/availability.

**Functionality:** Track internal resource pool for staffing opportunities.

**User Stories**
- As a Sales Rep, I want to see which resources are available before pitching a staff augmentation opportunity, so I don't oversell capacity.

### 4.14 Staff Augmentation — Opportunity Tracking Screen

**Elements:** Opportunity list (Client, Resource submitted, Interview stage, Feedback, Final status).

**Functionality:** Track submission-to-selection lifecycle per resource per client.

**User Stories**
- As a Sales Rep, I want to log interview feedback per round so we improve future submissions.
- As a Sales Manager, I want to prevent double-allocation of a resource across two active opportunities.

### 4.15 Documents & Proposals Screen

**Elements:** Document list (linked Account/Deal, version, uploader, date), upload button, version history view.

**Functionality:** Central document repository with version control.

**User Stories**
- As a Sales Rep, I want to upload a proposal and see its version history so I always send the latest approved copy.
- As a Delivery SME, I want to attach solution documents to a deal so Sales has them at final sending.

### 4.16 Activity Log / Timeline Screen

**Elements:** Chronological feed of calls, meetings, notes, follow-ups per lead/account/deal; filter by activity type.

**Functionality:** Full audit trail of interactions.

**User Stories**
- As a Sales Rep, I want to log a call or meeting note directly against an account so the history stays centralized.
- As a Sales Manager, I want to review the full activity timeline on a stalled deal so I can identify what's missing.

### 4.17 Settings / User Management Screen (Admin)

**Elements:** User list, role assignment, checklist template management, notification defaults.

**Functionality:** Admin controls for platform configuration.

**User Stories**
- As an Admin, I want to manage user roles so access stays aligned with actual responsibilities.
- As an Admin, I want to edit checklist templates so the platform can evolve as the pre-sales process changes.

---

## 5. Out of Scope

- Project delivery lifecycle management (post-contract execution)
- External customer-facing portal
- Advanced AI-based analytics beyond lead enrichment
- Third-party integrations beyond listed lead-sourcing tools (Apollo, Lusha, Red Drop)

---

## 6. Open Items Requiring Client Confirmation

- Source of company/account-level data (not present in current HubSpot export)
- Handling of incomplete lead records (missing email/phone)
- Staff Augmentation integration approach (embedded vs. standalone)
- Placement of supporting features (Notifications, Dashboard, Documents, Activity Log) — Phase 1 or later
- Document access/permission rules