# Project Blueprint: Remaining7 Discord Bot

## Overview 
**Name:** Remaining7 Discord Bot      
**Contributors:** nightwarrior5, remainingdelta    
**Objective:** To provide comprehensive economy, moderation, leveling, and event management features for the Remaining7 community Discord server. The bot centralizes server engagement by offering an R7 token system, automatic rewards, a redemption shop with real-world item tracking, and tools for competitive tournament management.   
**Server Link:** https://discord.gg/6MzrjS2X8k

---

## Goals 🎯
- Implement a persistent R7 Token Economy with MongoDB storage.
- Provide a token shop (`/shop`) where users can exchange tokens for real-world items (Brawl Pass, Nitro, PayPal) while respecting a monthly spending cap.
- Automatically track and reset the monthly budget for redemptions to prevent overspending.
- Include a Leveling System based on user activity (XP/Levels) and provide level-based bonuses.
- Introduce an Automatic Supply Drop system to encourage server activity and token distribution.
- Streamline Tournament & Ticketing Operations by providing specific commands for match reporting, bracket management- 

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
- **Ranking:** `/leaderboard` for tokens

### Tournament & Ticketing
- **Phase Management (`!starttourney`, `!endtourney`):** Tourney admin commands to switch the server between pre-tourney and main tourney phases. This includes resetting ticket counters, locking/reopening the general support channel, updating channel permissions, and automatically deleting old tickets.
- **Support Panels (`/tourney-panel`, `/pre-tourney-panel`):** Commands to post the interactive button panels for opening new tickets (for live match issues or pre-tourney questions).
- **Ticket Control (`!close`, `!c`):** Tourney admin command to close an active ticket.
- **Ticket Access (`/add`, `/remove`):** Tourney admin commands to manually add or remove a specific user to/from an active ticket channel.
- **Support Channel Lock (`!lock`, `!reopen`):** Tourney admin commands to temporarily lock the general support channel from non-staff members, with an automatic timer to reopen after 6 hours.
- **Hall of Fame (`/halloffame`):** Tourney admin to post structured, calculated results (prize money split: 50/25/15/10%) to the designated Hall of Fame channel.

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