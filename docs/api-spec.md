# AI Secretary System - API Requirements Specification

## Overview

An AI secretary that responds to user wishes ("I want to..." / "Please do...") with action-first proposals, then executes upon user confirmation.

---

## Core Principles

### 1. Action First
- **Never ask clarifying questions** before proposing
- Make assumptions and propose specific actions immediately
- Example: "evening" → assume "5pm", propose booking

### 2. Correction-Based Dialogue
- User sees concrete proposal first
- User corrects: "Change 5pm to 4pm" (easier than answering 10 questions upfront)

### 3. Delayed Credential Request
- Don't ask for login info upfront
- Request only when execution actually needs it
- "Execution requires login. Please provide credentials."

### 4. User Preference Learning (Future)
- Learn user preferences over time
- Example: User A prefers direct purchase links, User B prefers consultation via LINE

---

## API List

### Phase 1: Core Flow (Proposal & Confirmation)

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 1 | `/` | GET | Health check | ✅ Tested |
| 2 | `/api/v1/wish` | POST | Send wish, get action-first proposal | ✅ Tested |
| 3 | `/api/v1/task/{id}` | GET | Get task status | ✅ Tested |
| 4 | `/api/v1/task/{id}/revise` | POST | Revise proposal ("change to 4pm") | ✅ Tested |
| 5 | `/api/v1/task/{id}/confirm` | POST | Confirm and execute task | ✅ Tested |
| 6 | `/api/v1/tasks` | GET | List all tasks | ✅ Tested |

### Phase 2: Actual Execution Tools

| # | API/Tool | Description | Status |
|---|----------|-------------|--------|
| 7 | LINE Send | Send LINE message via Messaging API | ⏳ Code exists, needs config |
| 8 | Email Send | Send email via Gmail API | ⏳ Code exists, needs config |
| 9 | Web Browse | Browse/operate websites via Playwright | ⏳ Code exists, not connected |
| 10 | Form Fill | Fill forms on websites | ⏳ Code exists, not connected |
| 11 | Web Search | Search web for information | ⏳ Code exists, not connected |

### Phase 3: Credential Management

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 12 | `/api/v1/credentials` | POST | Store encrypted credentials | ❌ Not implemented |
| 13 | `/api/v1/credentials/{service}` | GET | Get credentials for service | ❌ Not implemented |
| 14 | `/api/v1/task/{id}/provide-credentials` | POST | Provide credentials for blocked task | ❌ Not implemented |

### Phase 4: User Preference Learning

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 15 | `/api/v1/preferences` | GET | Get user preferences | ❌ Not implemented |
| 16 | `/api/v1/preferences` | POST | Update user preferences | ❌ Not implemented |
| 17 | `/api/v1/task/{id}/feedback` | POST | Provide feedback on task execution | ❌ Not implemented |

### Phase 5: External Integrations

| # | API | Method | Description | Status |
|---|-----|--------|-------------|--------|
| 18 | `/webhook/line` | POST | LINE Webhook (receive messages) | ⏳ Code exists, needs config |

---

## API Details

### 2. POST /api/v1/wish

**Request:**
```json
{
  "wish": "Book a Shinkansen ticket from Shin-Osaka to Hakata on Dec 28th around 5pm"
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "message": "Action proposed. Please confirm to execute, or request revisions.",
  "proposed_actions": ["Book Shinkansen via EX Reservation for 5:00 PM Dec 28"],
  "proposal_detail": "[ACTION]\nBook Shinkansen ticket via EX Reservation...\n\n[DETAILS]\n- Route: Shin-Osaka -> Hakata\n- Time: Dec 28, 5:00 PM\n\n[NOTES]\n5pm is an assumption. Let me know if you want a different time.",
  "requires_confirmation": true
}
```

### 4. POST /api/v1/task/{id}/revise

**Request:**
```json
{
  "revision": "Change the time from 5pm to 4pm"
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "message": "Proposal revised. Please confirm to execute.",
  "proposed_actions": ["Book Shinkansen via EX Reservation for 4:00 PM Dec 28"],
  "proposal_detail": "[ACTION]\n...(updated with 4pm)...",
  "requires_confirmation": true
}
```

### 5. POST /api/v1/task/{id}/confirm

**Request:** (no body needed)

**Response (success):**
```json
{
  "task_id": "uuid",
  "status": "executing",
  "message": "Task execution started"
}
```

**Response (credentials needed):**
```json
{
  "task_id": "uuid",
  "status": "awaiting_credentials",
  "message": "Execution requires login credentials for EX Reservation",
  "required_credentials": ["ex_reservation"]
}
```

### 14. POST /api/v1/task/{id}/provide-credentials (Phase 3)

**Request:**
```json
{
  "service": "ex_reservation",
  "username": "user@example.com",
  "password": "encrypted_password"
}
```

**Response:**
```json
{
  "task_id": "uuid",
  "status": "executing",
  "message": "Credentials received. Resuming execution."
}
```

---

## Example User Flows

### Flow 1: PC Purchase Consultation
```
User: "I want to buy a new PC"
     ↓
System: [ACTION] Send LINE message to MDLmake for consultation
        [DETAILS] "Hello, I'm looking for a new PC for development work..."
        [NOTES] Assumed budget: $1,500. Correct if needed.
     ↓
User: Confirms → System sends LINE message
```

### Flow 2: Shinkansen Booking with Revision
```
User: "Book Shinkansen Shin-Osaka to Hakata on Dec 28 evening"
     ↓
System: [ACTION] Book via EX Reservation, Dec 28 5:00 PM
     ↓
User: "Change to 4pm"
     ↓
System: [ACTION] Book via EX Reservation, Dec 28 4:00 PM
     ↓
User: Confirms → System attempts booking
     ↓
System: "Credentials needed for EX Reservation"
     ↓
User: Provides credentials → System completes booking
```

### Flow 3: Tax Accountant Search
```
User: "I want to change my tax accountant"
     ↓
System: [ACTION] Post requirement on Zeirishi-Dot-Com
        [DETAILS] Looking for tax accountant, general requirements...
     ↓
User: "I need one specialized in real estate"
     ↓
System: [ACTION] Post requirement (updated: real estate specialty)
     ↓
User: Confirms → System operates website to post
```

---

## Test Status Summary

| Phase | APIs | Tested | Pending |
|-------|------|--------|---------|
| Phase 1 | 6 | 6 ✅ | 0 |
| Phase 2 | 5 | 0 | 5 (needs config) |
| Phase 3 | 3 | 0 | 3 (not implemented) |
| Phase 4 | 3 | 0 | 3 (not implemented) |
| Phase 5 | 1 | 0 | 1 (needs config) |
| **Total** | **18** | **6** | **12** |

---

## Next Steps

1. **Phase 2**: Connect LINE/Email/Browser tools to actual services
2. **Phase 3**: Implement credential management flow
3. **Phase 4**: Implement user preference learning
4. **Phase 5**: Configure LINE webhook
