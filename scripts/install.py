import subprocess
import os
import sys
from pathlib import Path

# Port the pc_control agent listens on for the parent web panel to connect to.
# Must match RemoteControlServer's default port in src/pc_control.py.
AGENT_PORT = 9999
FIREWALL_RULE_NAME = "Kid PC Monitor (agent)"

def find_pc_control():
    """Locate pc_control.py relative to this installer.

    The repo layout is fixed: this script lives in scripts/ and pc_control.py
    lives in src/, so we can find it without asking the user. We also check a
    couple of fallback locations in case the files were moved.
    """
    installer_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(installer_dir, "..", "src", "pc_control.py"),  # repo layout
        os.path.join(installer_dir, "pc_control.py"),               # alongside installer
        os.path.join(os.getcwd(), "pc_control.py"),                 # current directory
    ]
    for candidate in candidates:
        candidate = os.path.abspath(candidate)
        if os.path.exists(candidate):
            return candidate
    return None

def get_script_path():
    """Get the path to pc_control.py, auto-detecting when possible."""
    script_path = find_pc_control()

    if script_path:
        print(f"✅ Found pc_control.py: {script_path}")
        return script_path

    # Auto-detection failed — fall back to asking the user.
    print("⚠️  Could not auto-detect pc_control.py.")
    while True:
        custom_path = input("\nEnter full path to pc_control.py: ").strip()
        # Remove quotes if user copied from explorer
        custom_path = custom_path.strip('"').strip("'")

        if os.path.exists(custom_path) and custom_path.endswith('.py'):
            return os.path.abspath(custom_path)
        else:
            print("❌ File not found or not a .py file. Please try again.")

def create_task_with_power_settings():
    """Create scheduled task that runs even on battery power"""
    
    # Get script path from user
    script_path = get_script_path()
    if not script_path:
        return False
    
    pythonw_path = sys.executable.replace('python.exe', 'pythonw.exe')
    task_name = "KidPCMonitor"
    current_user = os.getenv('USERNAME')
    
    # Show what we're about to do
    print(f"\n📋 Task Configuration:")
    print(f"   Script: {script_path}")
    print(f"   Python: {pythonw_path}")
    print(f"   Task Name: {task_name}")
    print(f"   User Account: {current_user}")
    
    confirm = input("\nProceed with these settings? (y/n): ").lower()
    if confirm != 'y':
        print("❌ Setup cancelled.")
        return False
    
    # PowerShell script to create task with specific power settings
    ps_script = f'''
    $ErrorActionPreference = 'Stop'
    try {{
        # Create the action
        $action = New-ScheduledTaskAction -Execute "{pythonw_path}" -Argument "{script_path}" -WorkingDirectory "{os.path.dirname(script_path)}"
        
        # Create multiple triggers
        $triggers = @(
            (New-ScheduledTaskTrigger -AtStartup),
            (New-ScheduledTaskTrigger -AtLogon)
        )
        
        # Create principal (run with current user)
        $principal = New-ScheduledTaskPrincipal -UserId "{current_user}" -LogonType Interactive -RunLevel Highest
        
        # Create settings with power options
        $settings = New-ScheduledTaskSettingsSet `
            -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries `
            -StartWhenAvailable `
            -DontStopOnIdleEnd `
            -RestartCount 3 `
            -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Hours 0)
        
        # Register the task
        Register-ScheduledTask `
            -TaskName "{task_name}" `
            -Action $action `
            -Trigger $triggers `
            -Principal $principal `
            -Settings $settings `
            -Force
        
        # Verify task was actually created
        $task = Get-ScheduledTask -TaskName "{task_name}" -ErrorAction Stop
        Write-Host "SUCCESS: Task verified in Task Scheduler"
        Write-Host "Task Path: $($task.TaskPath)"
        Write-Host "Triggers: $($task.Triggers)"
        Write-Host "Principal: $($task.Principal)"
        exit 0
    }}
    catch {{
        Write-Host "ERROR: $_"
        Write-Host "Detailed error: $($_.Exception.Message)"
        exit 1
    }}
    '''
    
    try:
        # Run PowerShell script
        result = subprocess.run(
            ['powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
            capture_output=True,
            text=True
        )
        
        # Debug output
        print("\n=== PowerShell Output ===")
        print(result.stdout)
        if result.stderr:
            print("=== Errors ===")
            print(result.stderr)
        
        if result.returncode == 0:
            # Additional verification
            verify_cmd = f'schtasks /query /tn "{task_name}"'
            verify_result = subprocess.run(verify_cmd, shell=True, capture_output=True, text=True)
            
            if verify_result.returncode == 0:
                print("\n✅ Task successfully created and verified!")
                print(f"   - Triggers: At Startup + At Logon")
                print(f"   - Running as: {current_user}")
                print("\nYou can verify in Task Scheduler (taskschd.msc)")
                return True
            else:
                print("\n❌ Task creation failed verification")
                print("Try running this script as Administrator again")
                return False
        else:
            print("\n❌ Error creating task")
            if "Access is denied" in result.stderr:
                print("Please ensure you're running as Administrator")
            return False
            
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return False
    
def create_task_simple_schtasks():
    """Alternative using schtasks with XML template"""
    
    # Get script path from user
    script_path = get_script_path()
    if not script_path:
        return False
    
    python_path = sys.executable
    task_name = "KidPCMonitor"
    
    print(f"\n📋 Creating task with XML method...")
    
    # Create XML with proper power settings
    xml_content = f'''<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Kid PC Monitor - Manages computer usage time</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python_path}</Command>
      <Arguments>"{script_path}"</Arguments>
      <WorkingDirectory>{os.path.dirname(script_path)}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>'''
    
    try:
        # Write XML to temp file
        with open('task_config.xml', 'w', encoding='utf-16') as f:
            f.write(xml_content)
        
        # Import the task
        result = subprocess.run(
            f'schtasks /create /tn "{task_name}" /xml "task_config.xml" /f',
            shell=True,
            capture_output=True,
            text=True
        )
        
        # Clean up
        os.remove('task_config.xml')
        
        if result.returncode == 0:
            print("\n✅ Task created successfully with battery settings!")
            verify_task_settings(task_name)
            return True
        else:
            print(f"\n❌ Error: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        return False

def verify_task_settings(task_name):
    """Verify the power settings of a task"""
    
    # Query task and check settings
    query_cmd = f'schtasks /query /tn "{task_name}" /xml'
    result = subprocess.run(query_cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode == 0:
        xml = result.stdout
        battery_start = "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
        battery_stop = "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>" in xml
        
        print("\n📋 Task Power Settings:")
        print(f"   ✅ Can start on battery: {battery_start}")
        print(f"   ✅ Won't stop on battery: {battery_stop}")

def check_admin():
    """Check if running as administrator"""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

def port_check_command():
    """Return the OS-appropriate command to check if the agent port listens."""
    if sys.platform.startswith('win'):
        return f'netstat -an | findstr {AGENT_PORT}'
    elif sys.platform == 'darwin':
        # ss isn't available on macOS; lsof is the reliable option.
        return f'lsof -nP -iTCP:{AGENT_PORT} -sTCP:LISTEN'
    else:
        # Linux and other Unixes: ss is the modern default.
        return f'ss -tlnp | grep {AGENT_PORT}'

def print_port_check_hint():
    """Tell the user how to verify the agent is actually listening."""
    print("\n" + "=" * 45)
    print(f"💡 To verify the agent is listening on port {AGENT_PORT}, run:")
    print(f"   {port_check_command()}")
    print(f"\n   If nothing shows up, the agent isn't running. Run it in a")
    print(f"   console to see why:  python \"{find_pc_control() or 'src/pc_control.py'}\"")
    print("=" * 45)

def manual_firewall_command():
    """The netsh command a user can run by hand to open the agent port."""
    return (
        f'netsh advfirewall firewall add rule '
        f'name="{FIREWALL_RULE_NAME}" dir=in action=allow '
        f'protocol=TCP localport={AGENT_PORT}'
    )

def configure_firewall():
    """Add a Windows Firewall inbound rule for the agent port.

    The agent listens on AGENT_PORT so the parent web panel can connect to it.
    Without an inbound rule Windows Firewall blocks those connections, so the
    panel can't reach the kid PC. We make this idempotent by deleting any rule
    with the same name first, then adding a fresh one.
    """
    print(f"\n🔥 Windows Firewall: the agent listens on TCP port {AGENT_PORT} so")
    print("   the parent web panel can connect to this PC.")
    print("   Incoming connections must be allowed through the firewall.")

    confirm = input(
        f"\nAdd a firewall rule to allow incoming TCP port {AGENT_PORT}? (y/n): "
    ).lower()
    if confirm != 'y':
        print("\nℹ️  Skipped. To allow it later, run this in an admin prompt:")
        print(f"   {manual_firewall_command()}")
        return False

    # Remove any pre-existing rule with this name so we don't stack duplicates.
    subprocess.run(
        f'netsh advfirewall firewall delete rule name="{FIREWALL_RULE_NAME}"',
        shell=True, capture_output=True, text=True
    )

    result = subprocess.run(
        f'netsh advfirewall firewall add rule '
        f'name="{FIREWALL_RULE_NAME}" dir=in action=allow '
        f'protocol=TCP localport={AGENT_PORT}',
        shell=True, capture_output=True, text=True
    )

    if result.returncode == 0:
        print(f"\n✅ Firewall rule added: incoming TCP port {AGENT_PORT} allowed.")
        return True
    else:
        print("\n❌ Could not add firewall rule automatically.")
        if result.stdout.strip():
            print(result.stdout.strip())
        if result.stderr.strip():
            print(result.stderr.strip())
        print("\nYou can add it manually from an admin prompt:")
        print(f"   {manual_firewall_command()}")
        return False

def remove_firewall_rule():
    """Remove the agent firewall rule (used when removing the task)."""
    result = subprocess.run(
        f'netsh advfirewall firewall delete rule name="{FIREWALL_RULE_NAME}"',
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"✅ Firewall rule '{FIREWALL_RULE_NAME}' removed.")
    else:
        print("ℹ️  No matching firewall rule found.")

def remove_task():
    """Remove existing task"""
    task_name = "KidPCMonitor"
    print(f"\n🗑️  Removing task '{task_name}'...")
    
    result = subprocess.run(
        f'schtasks /delete /tn "{task_name}" /f',
        shell=True,
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("✅ Task removed successfully!")
    else:
        print("ℹ️  Task not found or already removed.")
    
if __name__ == "__main__":
    print("Kid PC Monitor - Task Scheduler Setup")
    print("=" * 45)
    
    if not check_admin():
        print("\n❌ This script needs to run as Administrator!")
        print("   Please right-click and select 'Run as administrator'")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    print("\nWhat would you like to do?")
    print("1. Create/Update scheduled task")
    print("2. Remove scheduled task")
    print("3. Exit")
    
    choice = input("\nChoice (1-3): ").strip()
    
    if choice == "1":
        print("\nCreating scheduled task with battery-friendly settings...\n")

        # Try PowerShell method first (most reliable)
        task_created = create_task_with_power_settings()
        if task_created:
            print("\n✅ Setup complete! Task will run even on laptops using battery.")
        else:
            print("\nTrying alternative method...")
            task_created = create_task_simple_schtasks()
            if task_created:
                print("\n✅ Setup complete using XML method!")
            else:
                print("\n❌ Could not create task. Please check the error messages above.")

        # The task only matters if the parent web panel can reach the agent,
        # which Windows Firewall blocks by default — offer to open the port.
        if task_created:
            configure_firewall()
            print_port_check_hint()

    elif choice == "2":
        remove_task()
        remove_firewall_rule()
    
    else:
        print("\nExiting...")
    
    input("\nPress Enter to close...")
