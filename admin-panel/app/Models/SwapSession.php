<?php

namespace App\Models;

use Illuminate\Database\Eloquent\Model;

class SwapSession extends Model
{
    protected $connection = 'exchange';
    protected $table = 'swap_sessions';
    public $timestamps = false;
    protected $guarded = ['*'];
}
