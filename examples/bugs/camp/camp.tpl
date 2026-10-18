include: share/base.yml

vars:
  # primary -> example.com, can change
  # secondary -> attacker.com, can change
  # aux -> none, can change

# please set trigger here
# e.g., trigger: trigger-for-camp.example.com

builds:
  primary:
    auto:
      setup: |
        origin = config.get("behavior", "")
        behavs = []
        
        origin += "\n".join(behavs)
        config["behavior"] = origin

  secondary:
    auto:
      setup: |
        origin = config.get("behavior", "")
        behavs = []
        
        origin += "\n".join(behavs)
        config["behavior"] = origin
