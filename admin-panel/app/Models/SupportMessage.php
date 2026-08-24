<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;

class SupportMessage extends Model
{
    protected $connection = 'exchange';
    protected $table = 'support_messages';
    public $timestamps = false;

    protected $fillable = ['message', 'sender', 'created_at'];

    public function ticket(): BelongsTo
    {
        return $this->belongsTo(SupportTicket::class, 'ticket_id');
    }
}
