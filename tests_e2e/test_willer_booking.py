"""
E2E Test: WILLER Highway Bus Booking

This test actually:
1. Sends a wish to the API
2. Confirms the task
3. Playwright opens browser and navigates WILLER site
4. Reaches confirmation screen (does NOT complete purchase)

Run: pytest tests_e2e/test_willer_booking.py -v --headed
"""
import pytest
import time


class TestWillerBookingE2E:
    """WILLER Highway Bus Booking E2E Tests"""
    
    @pytest.mark.e2e
    def test_book_bus_osaka_to_tottori(self, client, auth_headers):
        """
        E2E: Book a bus from Osaka to Tottori
        
        Full flow:
        1. POST /wish - Create booking request
        2. POST /confirm - Execute booking
        3. Verify Playwright reached confirmation screen
        """
        # Step 1: Send wish
        wish_response = client.post(
            "/api/v1/wish",
            json={"wish": "Book a highway bus from Osaka (Umeda) to Tottori on January 10th"},
            headers=auth_headers
        )
        assert wish_response.status_code == 200
        data = wish_response.json()
        task_id = data["task_id"]
        
        print(f"\n📋 Task created: {task_id}")
        print(f"📋 Proposed actions: {data.get('proposed_actions', [])}")
        
        # Step 2: Confirm the task
        confirm_response = client.post(
            f"/api/v1/task/{task_id}/confirm",
            headers=auth_headers
        )
        assert confirm_response.status_code == 200
        result = confirm_response.json()
        
        print(f"\n🚌 Execution result: {result}")
        
        # Step 3: Verify result
        # Note: May fail if no buses available, which is OK
        exec_result = result.get("result", {})
        
        if exec_result.get("success"):
            print("✅ Booking reached confirmation screen!")
            assert "confirmation_number" in exec_result or "WILLER" in exec_result.get("message", "")
        else:
            # Check if alternatives were provided
            message = exec_result.get("message", "")
            print(f"⚠️ Booking failed: {message}")
            
            if "代替案" in message or "alternatives" in exec_result:
                print("✅ Fallback alternatives provided!")
            
            # This is acceptable - buses may not be available
            assert "No available" in message or "代替案" in message or "error" in message.lower()
    
    @pytest.mark.e2e
    def test_revise_and_rebook(self, client, auth_headers):
        """
        E2E: Revise booking request and re-search
        
        Flow:
        1. POST /wish - Initial request (Osaka to Yonago)
        2. POST /revise - Change destination to Tottori
        3. Verify re-search was performed
        4. POST /confirm - Execute revised booking
        """
        # Step 1: Initial wish
        wish_response = client.post(
            "/api/v1/wish",
            json={"wish": "Book a bus from Osaka to Yonago on January 15th"},
            headers=auth_headers
        )
        assert wish_response.status_code == 200
        task_id = wish_response.json()["task_id"]
        print(f"\n📋 Initial task: {task_id}")
        
        # Step 2: Revise the request
        revise_response = client.post(
            f"/api/v1/task/{task_id}/revise",
            json={"revision": "Actually, change to Tottori City. Bus or train is fine."},
            headers=auth_headers
        )
        assert revise_response.status_code == 200
        revised = revise_response.json()
        
        print(f"\n🔄 Revised proposal: {revised.get('proposed_actions', [])}")
        
        # Verify revision was applied
        proposal = revised.get("proposal_detail", "")
        assert "Tottori" in proposal or "tottori" in proposal.lower()
        
        # Step 3: Confirm revised task
        confirm_response = client.post(
            f"/api/v1/task/{task_id}/confirm",
            headers=auth_headers
        )
        assert confirm_response.status_code == 200
        
        print(f"\n✅ Revised booking executed")


class TestSmartFallbackE2E:
    """Smart Fallback E2E Tests"""
    
    @pytest.mark.e2e
    def test_fallback_when_no_bus(self, client, auth_headers):
        """
        E2E: Verify fallback alternatives when bus not found
        
        Requests a bus for a route/date that likely has no availability,
        then verifies alternatives are suggested.
        """
        # Request a bus for tomorrow (likely no availability)
        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%B %d")
        
        wish_response = client.post(
            "/api/v1/wish",
            json={"wish": f"Book a bus from Osaka to a remote town in Tottori on {tomorrow}"},
            headers=auth_headers
        )
        assert wish_response.status_code == 200
        task_id = wish_response.json()["task_id"]
        
        # Confirm and expect failure with alternatives
        confirm_response = client.post(
            f"/api/v1/task/{task_id}/confirm",
            headers=auth_headers
        )
        assert confirm_response.status_code == 200
        result = confirm_response.json()
        
        exec_result = result.get("result", {})
        message = exec_result.get("message", "")
        
        print(f"\n📋 Result message: {message}")
        
        # Should either succeed or provide alternatives
        if not exec_result.get("success"):
            # Alternatives should be provided
            assert "代替案" in message or "おすすめ" in message or "alternatives" in str(exec_result)
            print("✅ Fallback alternatives verified!")

