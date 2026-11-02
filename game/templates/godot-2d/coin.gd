extends Area2D
## Collectible: emits `collected` and frees itself when the player (any PhysicsBody2D) touches it.
signal collected

func _ready() -> void:
	add_to_group("coins")
	body_entered.connect(_on_body_entered)

func _on_body_entered(_body: Node2D) -> void:
	collected.emit()
	queue_free()
