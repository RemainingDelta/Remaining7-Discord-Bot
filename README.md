# Project Blueprint: Remaining7 Discord Bot

## Overview 
**Name:** Remaining7 Discord Bot      
**Contributors:** nightwarrior5, remainingdelta    
**Objective:** To provide comprehensive economy, moderation, leveling, and event management features for the Remaining7 community Discord server, supporting over 15k members. The bot centralizes server engagement by offering an R7 token system, automatic rewards, a redemption shop with real-world item tracking, and tools for competitive tournament management.   
**Server Link:** https://discord.gg/6MzrjS2X8k

---

## Goals 🎯
- Implement a persistent R7 Token Economy with MongoDB storage.
- Provide a token shop (`/shop`) where users can exchange tokens for real-world items (Brawl Pass, Nitro, PayPal) while respecting a monthly spending cap.
- Automatically track and reset the monthly budget for redemptions to prevent overspending.
- Include a Leveling System based on user activity (XP/Levels) and provide level-based bonuses.
- Introduce an Automatic Supply Drop system to encourage server activity and token distribution.
- Streamline Tournament & Ticketing Operations by providing specific commands for match reporting and bracket management.
- Automate maintenance of event channels (`#red-event`, `#blue-event`, `#green-event`) to ensure messages are cleared before they exceed the 14-day bulk-delete limit.
- Implement a rapid-response security protocol to instantly isolate compromised accounts and purge malicious content from all server channels.
---

## Tech Stack 

### Backend / Bot Core
- **Framework:** `discord.py` 
- **Database:** MongoDB 


---

## Core Functionalities 

### R7 Token Economy
- **Token Management:** `/balance`, `/give` (Admin), `/setbalance` (Admin).
- **Daily Rewards:** `/daily` command with Level-based bonus multiplier.
- **Supply Drop:** `/drop` (Admin) timed automatic drops (on average every 6 hours with random delay).

### Shop & Budget System
- **Shop Display:** `/shop` (lists items, prices, and descriptions).
- **Purchasing:** `/buy` with strict dropdown menu of valid items and price check.
- **Redemption & Budget:** `/redeem` creates a staff ticket and increments a database counter.
- **Monthly Cap:** Automatically checks and enforces a **\$50.00 monthly budget** reset at the start of every month.
- **Budget Tracking:** `/checkbudget` shows spent vs. remaining budget based on item real-world dollar value.

### Leveling & Leaderboards
- **Leveling:** Tracks user XP and level progress.
- **Progress Check:** `/level` shows individual progress bar and next level EXP goal.
- **Token Ranking:** `/leaderboard` for tokens
- **Level Ranking:** `/levels_leaderboard` for tokens


### Tournament & Ticketing
- **Phase Management (`!starttourney`, `!endtourney`):** Tourney admin commands to switch the server between pre-tourney and main tourney phases. This includes resetting ticket counters, locking/reopening the general support channel, updating channel permissions, and automatically deleting old tickets.
- **Live Queue Dashboard:** A real-time, auto-updating embed (every 15s) posted in the main support channel. It displays the **"Currently Serving"** ticket number and the total number of users **"In Line"**, complete with a relative "Last Updated" timestamp.
- **Queue Status (`/queue`):** Allows users inside an active ticket to check their specific position in the line (e.g., "3/10") and see their wait status.
- **Support Panels (`/tourney-panel`, `/pre-tourney-panel`):** Commands to post the interactive button panels for opening new tickets (for live match issues or pre-tourney questions).
- **Ticket Control (`!close`, `!c`):** Tourney admin command to close an active ticket. Automatically identifies and deletes the oldest archived tickets if the closed category reaches the Discord 50-channel limit, ensuring new tickets can always be closed safely. 
- **Ticket Deletion (`!delete`, `!del`):** A command-based backup to manually delete a ticket channel and save the transcript (useful if button interactions fail).
- **Ticket Reopen (`!reopen`):** Reopens a closed ticket, moving it from the Closed category back to the Active category and restoring user permissions.
- **Ticket Access (`/add`, `/remove`):** Tourney admin commands to manually add or remove a specific user to/from an active ticket channel.
- **Support Channel Lock (`!lock`, `!reopen`):** Tourney admin commands to temporarily lock the general support channel from non-staff members, with an automatic timer to reopen after 6 hours.
- **Blacklist Management (`/blacklist add`, `/blacklist remove`, `/blacklist list`):** Stores blacklisted user through their Discord id, along with their matcherino profile, reason for blacklist, and their alts. 
- **Hall of Fame (`/hall-of-fame`):** Tourney admin to post structured, calculated results (prize money split: 50/25/15/10%) to the designated Hall of Fame channel.

### Tourney Admin Compensation System
- **Payout Tracking:** `/payout-add` records debts to tourney admins using unique Batch IDs ("receipts"). Supports **Split** (divides amount evenly) or **Flat** (full amount each) modes with reason logging.
- **Ledger Management:** `/payout-list` displays a live view of all outstanding tourney admin balances.
- **Smart History:** `/payout-history` displays a log of multi-user payouts. It dynamically filters the view to show *only* users who have not yet been paid for that specific event (hides users who have been reset).
- **Cash Out:** `/payout-reset` clears a staff member's balance and "shreds" their unpaid receipts, removing them from the pending history log.

### Event Maintenance
- **Automated Monitoring**: A daily background task (12:00 AM ET) scans the three event channels (`#red-event`, `#blue-event`, `#green-event`).
- **Smart Alerts**: If the oldest message in a channel is 7 days or older, an alert is sent to `#event-staff` containing a "Purge" button. This prevents messages from exceeding Discord's 14-day limit for bulk deletion.
- **Manual Cleanup**: `/clear-red`, `/clear-blue`, `/clear-green` allow Event Staff to manually wipe channels instantly.
- **Payout Automation**: `/event-rewards` (Admin Only) parses announcement messages (Format: `@User [Amount]`) to batch-distribute tokens. It includes a confirmation preview and prevents duplicate payouts.
- **Safety Checks**: These commands are restricted to the `#event-staff` channel and require the Event Staff or Admin role.

### Security System
- **Hacked Protocol:** `/hacked` (Slash) or `!hacked` (Reply) to instantly secure a compromised account.
- **Automated Cleanup:** triggers a 7-day timeout, flags the user in the database, and recursively purges their recent messages from **Text, Voice, and Thread** channels.
- **Recovery:** `/unhacked` removes the timeout and database flag once the user recovers their account.
- **Visibility:** `/hackedlist` displays all currently flagged/compromised users.

### Admin Tools
- **Permissions:** `/perm` (Admin) Add/Remove ability to use staff commands.

---

## Setup & Run Instructions 

This bot requires Python 3.10+ and a MongoDB Atlas database.

1. **Clone the Repository**
    ```bash
    git clone https://github.com/RemainingDelta/Remaining7-Discord-Bot
    cd Remaining7-Discord-Bot
    ``` 

2. **Setup Virtual Environment & Dependencies**
    ```bash
    python -m venv venv
    source venv/bin/activate  # Linux/macOS
    # or venv\Scripts\activate on Windows
    pip install -r requirements.txt
    ```

3. **Configure Environment Variables**
    This bot requires secrets to be set as environment variables on your hosting platform (or locally in a `.env` file). Reference the `.env.example` file for necessary keys.

    You **MUST** set at least the following:
    ```
    DISCORD_TOKEN= [Your Bot Token]
    MONGO_URI= [Your MongoDB Atlas Connection String]
    ```

4. **Update Configuration**
    Verify and update critical IDs in `features/config.py` (e.g., `ADMIN_ROLE_ID`, `GENERAL_CHANNEL_ID`) with your server's live IDs.

5. **Run the Bot**
    ```bash
    python main.py
    ```

---

## Future Roadmap 
- Budget Fixes
- Tokens while messaging fixes
- Update general server ticket system 
- Level Leaderboard View Revamp
- Tourney stats after running `!endtourney`
- Bug: `!endtourney` sometimes doesn't delete the live tournament queue embeded
