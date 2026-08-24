<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Illuminate\Database\Eloquent\Relations\HasMany;

class SupportTicket extends Model
{
    protected $connection = 'exchange';
    protected $table = 'support_tickets';
    public $timestamps = false;

    protected $fillable = ['status', 'updated_at'];

    public function messages(): HasMany
    {
        return $this->hasMany(SupportMessage::class, 'ticket_id')->orderBy('id');
    }

    public function webUser(): BelongsTo
    {
        return $this->belongsTo(WebUser::class, 'web_user_id');
    }
}
