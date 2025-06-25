# Exam Retake Implementation

## Overview
This document describes the implementation of exam retake functionality in the SmartExaM system.

## Features Implemented

### 1. Database Changes
- Added `can_retake` column to the `Result` model (Boolean, default=False)
- Migration script provided to update existing databases

### 2. Admin Controls
- Toggle button in admin dashboard to enable/disable retakes for specific student results
- Visual indicators showing retake status for each student result
- Retake permissions are managed per individual result, not per test

### 3. Student Experience
- Students can only retake tests when `can_retake = True` for their result
- Retake button appears in place of "Completed" status when retake is enabled
- Clear messaging about retake permissions

### 4. Retake Logic
- When a student retakes a test:
  - Old result is deleted from the database
  - New result is saved with `can_retake = False`
  - All security logging and scoring works normally
  - Test session management prevents cheating during retakes

### 5. Security Features
- Retakes follow the same security protocols as original tests
- Session management prevents access to learning resources during retakes
- All retake activities are logged for audit purposes

## Usage Instructions

### For Admins:
1. View test results in the dashboard
2. Use "Enable Retake" button to allow a student to retake a specific test
3. Use "Disable Retake" button to revoke retake permission

### For Students:
1. View available tests page
2. If retake is enabled, "Retake Test" button will appear
3. Take the test normally - old result will be automatically replaced

## Technical Implementation

### Files Modified:
- `models.py` - Added can_retake column
- `app.py` - Added retake logic and routes
- `templates/dashboard.html` - Added admin retake controls
- `templates/available_tests.html` - Added student retake interface

### Migration:
Run `python add_retake_column.py` to add the retake column to existing databases.

### Testing:
Run `python test_retake.py` to set up test data for retake functionality testing.
